"""岗位采集爬虫（步骤三：短任务采集）。

从多个互联网招聘来源采集岗位记录，按「统一字段」核对后返回标准字段。
专利要求：短任务采集——一次只采集一条/一页，抽取后核对字段名是否与
统一字段一致，一致才写库。

依赖：requests + BeautifulSoup（可选 lxml 加速）；JS 渲染站点用 Selenium/Playwright。

注意：真实招聘平台（Boss直聘、智联、猎聘、前程无忧等）多有反爬与登录墙，
生产环境须遵守 robots.txt 与平台服务条款，并优先使用平台官方 API / 合法数据源。
本模块提供通用 HTML 采集能力 + 可插拔数据源适配器。
"""
import re
import time
import requests
from bs4 import BeautifulSoup

import schema

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# 各来源字段名 -> 统一字段 的别名映射（多来源字段结构不统一，统一到 schema.JOB_FIELDS）
FIELD_ALIASES = {
    "岗位名称": ["岗位名称", "职位名称", "职位", "title", "jobTitle", "jobName", "positionName"],
    "单位名称": ["单位名称", "公司名称", "企业名称", "company", "companyName", "corpName"],
    "岗位链接": ["岗位链接", "链接", "url", "jobUrl", "link", "href", "detailUrl"],
    "投递入口地址": ["投递入口地址", "投递地址", "申请地址", "applyUrl", "entryAddr"],
    "投递入口类型": ["投递入口类型", "入口类型", "entryType", "applyType"],
    "岗位描述": ["岗位描述", "职位描述", "工作内容", "description", "jobDesc", "jd", "desc"],
    "城市": ["城市", "工作地点", "工作城市", "city", "workCity", "location", "cityName"],
    "行业": ["行业", "所属行业", "industry", "industryName"],
    "公司": ["公司", "company"],
    "薪资": ["薪资", "工资", "salary", "salaryDesc"],
    "学历": ["学历", "jobDegree", "degree", "学历要求"],
    "经验": ["经验", "jobExperience", "experience", "经验要求"],
    "技能": ["技能", "skills", "skill", "技术栈"],
    "已沟通": ["已沟通", "contact", "friendStatus", "haveContacted"],
}


def normalize_fields(raw: dict) -> dict:
    """把来源字段映射到统一字段，只保留统一字段白名单内的字段名（核对）。"""
    out = {}
    for std_name, aliases in FIELD_ALIASES.items():
        for a in aliases:
            if a in raw and raw[a] not in (None, ""):
                val = raw[a]
                if isinstance(val, list):  # 如 jobLabels 是列表
                    val = "、".join(str(x) for x in val)
                out[std_name] = str(val).strip()
                break
    # 补齐缺失的统一字段（后续关键字段缺损检查会剔除）
    for f in schema.JOB_FIELDS:
        out.setdefault(f, "")
    # 单位名称与公司同义：公司为空时用单位名称补齐（禁忌公司过滤依赖此字段）
    if not out.get("公司") and out.get("单位名称"):
        out["公司"] = out["单位名称"]
    return out


def fetch_html(url: str, timeout: int = 15, retries: int = 2, **kwargs) -> str:
    """带重试与限速的 HTML 抓取。支持本地文件路径与 http(s) URL。"""
    import os
    if url.startswith("file://"):
        url = url[len("file://"):]
    if os.path.isfile(url):  # 本地文件（演示用）
        with open(url, encoding="utf-8") as f:
            return f.read()
    last = None
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout, **kwargs)
            r.raise_for_status()
            r.encoding = r.apparent_encoding or "utf-8"
            return r.text
        except Exception as e:  # noqa
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"抓取失败 {url}: {last}")


def fetch_html_js(url: str, wait: int = 3) -> str:
    """JS 渲染抓取（用 Selenium 无头浏览器加载动态页面后返回渲染后的 HTML）。

    适用于招聘岗位列表由前端 JS 动态加载的站点（如 BOSS直聘、拉勾等）。
    需本机有 Chrome/Edge。
    """
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    opts = Options()
    opts.add_argument("--headless")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    driver = webdriver.Chrome(options=opts)
    try:
        driver.get(url)
        driver.implicitly_wait(wait)
        return driver.page_source
    finally:
        driver.quit()


def _resolve_url(url: str, page: int) -> str:
    """若 url 含 {page} 占位符则替换，否则返回原 url。"""
    return url.format(page=page) if "{page}" in url else url



class HtmlJobSource:
    """通用 HTML 岗位列表采集源。

    source 配置示例:
    {
        "name": "示例招聘站",
        "url": "https://example.com/jobs",
        "item_selector": "li.job-item",        # 每个岗位条目的 CSS 选择器
        "fields": {                              # 字段名 -> CSS 选择器（相对 item）
            "岗位名称": "h3.title",
            "单位名称": "span.company",
            "岗位链接": "a.detail",
            "城市": "span.city",
            "岗位描述": "p.desc",
        },
        "base_url": "https://example.com",       # 相对链接补全
    }
    """

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.name = cfg.get("name", cfg.get("url", "source"))

    def collect(self) -> list:
        pages = int(self.cfg.get("pages", 1))
        render_js = bool(self.cfg.get("render_js", False))
        delay = float(self.cfg.get("delay", 0.5))
        jobs = []
        for p in range(1, pages + 1):
            url = _resolve_url(self.cfg["url"], p)
            html = fetch_html_js(url) if render_js else fetch_html(url)
            soup = BeautifulSoup(html, "lxml")
            items = soup.select(self.cfg.get("item_selector", "li"))
            if not items:
                break
            for it in items:
                jobs.append(self._parse_item(it))
            time.sleep(delay)  # 限速，礼貌抓取
        return jobs

    def _parse_item(self, it) -> dict:
        raw = {}
        for field, sel in self.cfg.get("fields", {}).items():
            el = it.select_one(sel)
            if field in ("岗位链接", "投递入口地址") and el and el.get("href"):
                raw[field] = _abs_url(el["href"], self.cfg.get("base_url"))
            elif el:
                raw[field] = el.get_text(" ", strip=True)
        raw.setdefault("投递入口类型", "")
        raw["投递入口类型"] = _classify_entry(raw.get("投递入口地址", ""), raw.get("投递入口类型", ""))
        return normalize_fields(raw)


def _abs_url(url: str, base: str) -> str:
    if not url:
        return ""
    if url.startswith("http"):
        return url
    if base:
        return base.rstrip("/") + "/" + url.lstrip("/")
    return url


def _classify_entry(addr: str, preset: str) -> str:
    """投递入口四分类自动判定（与 delivery.classify_entry 一致）。"""
    if preset in ("Web表单", "邮件", "API", "半自动"):
        return preset
    a = (addr or "").lower()
    if not a.strip():
        return "半自动"
    if a.startswith("mailto") or re.match(r"^[\w.\-]+@[\w.\-]+\.\w+$", addr or ""):
        return "邮件"
    if "api" in a:
        return "API"
    return "Web表单"


def search_platform(platform_key, keyword, pages=1, city=""):
    """用已登录会话在指定平台真实检索岗位。返回 list[岗位dict]。

    依赖 session.py 保存的登录态；未登录会得到空结果（或需先扫码登录）。
    """
    import platforms as plat
    import session

    p = plat.get(platform_key)
    if not p:
        return []
    if not session.has_session(platform_key):
        return []  # 未登录，无法检索

    driver = session.get_logged_in_browser(platform_key, headless=True)
    jobs = []
    try:
        for pg in range(1, pages + 1):
            url = p["search_url"]
            for k, v in {"keyword": keyword, "city": city, "page": pg}.items():
                url = url.replace("{" + k + "}", str(v))
            driver.get(url)
            time.sleep(3)  # 等待渲染
            soup = BeautifulSoup(driver.page_source, "lxml")
            items = soup.select(p.get("item_selector", "li"))
            if not items:
                break
            for it in items:
                raw = {}
                for field, sel in p.get("fields", {}).items():
                    el = it.select_one(sel)
                    if field in ("岗位链接", "投递入口地址") and el and el.get("href"):
                        raw[field] = _abs_url(el["href"], "")
                    elif el:
                        raw[field] = el.get_text(" ", strip=True)
                raw.setdefault("投递入口类型", "")
                raw["投递入口类型"] = _classify_entry(raw.get("投递入口地址", ""), raw.get("投递入口类型", ""))
                jobs.append(normalize_fields(raw))
            time.sleep(0.5)
    finally:
        driver.quit()
    return jobs

def collect_from_sources(sources) -> list:
    """遍历多个来源，采集并核对字段。返回 list[岗位dict]。"""
def search_via_requests(platform_key, keyword, city="", pages=1):
    """用保存的登录 cookie 通过 requests 检索（不启动浏览器，不被反爬检测）。

    优先走平台 JSON API（如 Boss直聘 wapi），否则抓取搜索页 HTML 解析。
    """
    import requests
    import platforms as plat
    import session

    p = plat.get(platform_key)
    cookies = session.load_session(platform_key)
    if not cookies:
        return []
    cookie_dict = {c["name"]: c["value"] for c in cookies if c.get("value")}
    jobs = []

    api_url = p.get("api_url")
    if api_url:
        for pg in range(1, pages + 1):
            url = api_url
            for k, v in {"keyword": keyword, "city": city, "page": pg}.items():
                url = url.replace("{" + k + "}", str(v))
            r = requests.get(url, cookies=cookie_dict, headers=DEFAULT_HEADERS, timeout=15)
            data = r.json()
            job_list = _dig(data, p.get("api_jobs_path", ""))
            if not isinstance(job_list, list):
                break
            for item in job_list:
                raw = {}
                for std, src in p.get("api_field_map", {}).items():
                    raw[std] = _dig(item, src)
                raw.setdefault("投递入口类型", "")
                jobs.append(normalize_fields(raw))
    else:
        for pg in range(1, pages + 1):
            url = p["search_url"]
            for k, v in {"keyword": keyword, "city": city, "page": pg}.items():
                url = url.replace("{" + k + "}", str(v))
            r = requests.get(url, cookies=cookie_dict, headers=DEFAULT_HEADERS, timeout=15)
            soup = BeautifulSoup(r.text, "lxml")
            items = soup.select(p.get("item_selector", "li"))
            if not items:
                break
            for it in items:
                raw = {}
                for field, sel in p.get("fields", {}).items():
                    el = it.select_one(sel)
                    if field in ("岗位链接", "投递入口地址") and el and el.get("href"):
                        raw[field] = _abs_url(el["href"], "")
                    elif el:
                        raw[field] = el.get_text(" ", strip=True)
                raw.setdefault("投递入口类型", "")
                jobs.append(normalize_fields(raw))
    return jobs


def _dig(obj, path):
    """按点号路径取值，找不到返回空串。取值可以是任意类型（含 list/dict）。"""
    cur = obj
    for k in str(path or "").split("."):
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        elif isinstance(cur, list) and k.isdigit() and int(k) < len(cur):
            cur = cur[int(k)]
        else:
            return ""
    return cur

    all_jobs = []
    for src in sources:
        collector = HtmlJobSource(src)
        jobs = collector.collect()
        all_jobs.extend(jobs)
        time.sleep(0.5)  # 限速（礼貌抓取）
    return all_jobs
