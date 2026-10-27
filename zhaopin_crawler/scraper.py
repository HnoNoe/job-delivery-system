# -*- coding: utf-8 -*-
"""
scraper.py —— 智联招聘采集核心
===============================
为什么这样抓（实测结论，2026-10-25）：

1. 智联的检索页 `sou.zhaopin.com/?jl=城市码&kw=关键词` 是**服务端渲染**的，
   岗位数据直接写在页面里的 `window.__INITIAL_STATE__.positionList` 中（每次 20 条）；
2. 这个页面**不需要登录**就能看，所以本工具不需要扫码；
3. 但它有反爬：连续用 requests 直接请求，从第 2 次开始会被跳到
   「Security Verification」验证页（约 2KB 的空白页）。用**真实浏览器**（本机 Edge）
   打开就不会被拦，所以这里用 Playwright 驱动浏览器；
4. 该页面不支持翻页（实测 `hasMore=False`、`?p=2` 返回的仍是第一页），
   所以「抓几百条」是靠**多关键词 × 多城市组合累加**实现的。
"""

import time
import urllib.parse
from pathlib import Path

from playwright.sync_api import sync_playwright

from config import PER_COMBO, SEARCH_URL
from parser import dedupe_key, is_meaningful, parse_position
from utils import human_sleep, now_str

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});
window.chrome = window.chrome || {runtime: {}};
"""

WAIT_STATE_JS = ("() => !!(window.__INITIAL_STATE__ "
                 "&& window.__INITIAL_STATE__.positionList)")


class ZhaopinScraper:
    def __init__(self, settings, root: Path, logger):
        self.s = settings
        self.root = Path(root)
        self.log = logger
        self.records = []
        self.seen = set()
        self.requests = 0
        self.failed = 0
        self._fail_streak = 0
        self.started = time.time()
        self._pw = None
        self._ctx = None
        self._page = None
        self._browser_name = ""

    # ------------------------------------------------------------------
    def run(self):
        try:
            self._start_browser()
            try:
                self._crawl()
            except Exception:
                # 无头模式容易被反爬识别，自动换有窗口模式重试一次
                if self.s.headless and self._page is not None:
                    self.log.warning("无头模式可能被识别，自动切换为有窗口模式重试……")
                    self._restart_headed()
                    self._crawl()
                else:
                    raise
        except KeyboardInterrupt:
            self.log.warning("收到中断信号，保存已采集的数据……")
        finally:
            self._shutdown()

        return self.records, {
            "mode": "browser",
            "browser": self._browser_name,
            "requests": self.requests,
            "failed": self.failed,
            "elapsed": round(time.time() - self.started, 1),
            "finished_at": now_str(),
        }

    # ------------------------------------------------------------------
    # 浏览器
    # ------------------------------------------------------------------
    def _start_browser(self):
        profile = self.root / "browser_data"
        profile.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()

        args = [
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-features=Translate,OptimizationHints",
        ]
        common = dict(
            headless=self.s.headless,
            args=args,
            viewport={"width": 1440, "height": 900},
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
        )
        last = None
        for channel in ("msedge", "chrome", None):
            try:
                kw = dict(common)
                if channel:
                    kw["channel"] = channel
                self._ctx = self._pw.chromium.launch_persistent_context(str(profile), **kw)
                self._browser_name = channel or "chromium"
                break
            except Exception as e:  # noqa: BLE001
                last = e
        if self._ctx is None:
            raise RuntimeError(
                "无法启动浏览器。请确认已安装 Edge 或 Chrome；"
                "或执行 `python -m playwright install chromium` 后重试。\n"
                f"原始错误：{last}"
            )
        self._ctx.add_init_script(STEALTH_JS)
        self._ctx.set_default_timeout(30000)
        self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
        self.log.info(f"浏览器已启动（{self._browser_name}，headless={self.s.headless}）")

    def _restart_headed(self):
        try:
            if self._ctx:
                self._ctx.close()
        except Exception:
            pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        self._ctx = self._pw = self._page = None
        self.s.headless = False
        self._start_browser()

    def _shutdown(self):
        try:
            if self._ctx:
                self._ctx.close()
        except Exception:
            pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 取一个「关键词 × 城市」组合的 20 条
    # ------------------------------------------------------------------
    def _fetch_combo(self, keyword: str, city_code: str):
        url = f"{SEARCH_URL}?jl={city_code}&kw={urllib.parse.quote(keyword)}"
        for attempt in range(self.s.max_retry + 1):
            try:
                self._page.goto(url, wait_until="domcontentloaded", timeout=60000)
                self._page.wait_for_function(WAIT_STATE_JS, timeout=20000)
                items = self._page.evaluate(
                    "() => (window.__INITIAL_STATE__ || {}).positionList || []")
                self.requests += 1
                if items:
                    self._fail_streak = 0
                    return items, url
                # 拿到了页面结构但没有数据：可能是被验证页拦了
                title = ""
                try:
                    title = self._page.title()
                except Exception:
                    pass
                self.log.warning(f"该组合没有数据（标题：{title!r}），第 {attempt + 1} 次重试")
            except Exception as e:  # noqa: BLE001
                self.requests += 1
                msg = str(e).splitlines()[0][:110]
                self.log.warning(f"打开失败（第 {attempt + 1} 次）：{msg}")

            if attempt < self.s.max_retry:
                self._safe_wait(6 + attempt * 4)
        self.failed += 1
        self._fail_streak += 1
        return [], url

    def _safe_wait(self, seconds):
        """页面可能已被关闭，用纯 sleep 更安全。"""
        time.sleep(seconds)

    # ------------------------------------------------------------------
    def _crawl(self):
        queries = self.s.queries()
        total = min(len(queries), max(1, self.s.max_jobs // PER_COMBO + 1))
        self.log.info(f"开始采集：{len(queries)} 个组合，最多取前 {total} 个组合，"
                      f"上限 {self.s.max_jobs} 条")

        for i, (kw, city, code) in enumerate(queries, 1):
            if len(self.records) >= self.s.max_jobs:
                self.log.info("已达到条数上限，提前结束。")
                break
            if self._fail_streak >= 5:
                self.log.error("连续 5 个组合都失败，疑似被反爬拦截，停止采集。")
                break

            items, url = self._fetch_combo(kw, code)
            added = self._collect(items, kw, city) if items else 0
            self.log.info(
                f"[{i}/{len(queries)}] {city} · {kw} → 拿到 {len(items)} 条，"
                f"新增 {added} 条（累计 {len(self.records)}）"
            )
            human_sleep(self.s.min_delay, self.s.max_delay, "翻页", self.log)

    # ------------------------------------------------------------------
    def _collect(self, items, keyword: str, city: str) -> int:
        added = 0
        for item in items:
            try:
                rec = parse_position(item, keyword=keyword, source_city=city)
            except Exception as e:  # noqa: BLE001
                self.log.debug(f"解析失败：{e}")
                continue
            if not is_meaningful(rec):
                continue
            key = dedupe_key(rec)
            if key in self.seen:
                continue
            self.seen.add(key)
            self.records.append(rec)
            added += 1
            if len(self.records) >= self.s.max_jobs:
                break
        return added
