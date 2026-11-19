"""通用探查脚本：读取某个已登录平台的消息列表（只读），用于校准回复检测。

Boss 已实测通过；智联/拉勾/猎聘/前程无忧的消息页结构未实测，第一次用它们时：
1. 先在应用里完成该平台登录（第②阶段扫码）；
2. 运行 `.venv\\Scripts\\python.exe probe_platform_chat.py zhilian`
3. 把 `data/chat_probe_<平台>.json` 里的 URL / DOM 样本发出来，据此补
   `platforms.py` 中该平台的 `chat_item_selector` 或字段映射。

用法：python probe_platform_chat.py <platform_key>   # boss / zhilian / lagou / liepin / job51
"""
import io
import json
import sys
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import config  # noqa: E402
import db  # noqa: E402
import platforms  # noqa: E402
import replies  # noqa: E402
import session  # noqa: E402

PLATFORM = (sys.argv[1] if len(sys.argv) > 1 else "boss").strip()
OUT = Path(config.DATA_DIR) / ("chat_probe_%s.json" % PLATFORM)


def log(msg):
    print(msg, flush=True)


def tasks_for_latest_user():
    db.init_db()
    with db.get_conn() as conn:
        row = conn.execute("SELECT user_id FROM delivery_tasks ORDER BY task_id DESC LIMIT 1").fetchone()
        if not row:
            return [], None
        uid = row["user_id"]
        rows = conn.execute(
            "SELECT task_id, job_name, unit_name, status FROM delivery_tasks "
            "WHERE user_id=? ORDER BY task_id", (uid,)).fetchall()
    return [dict(r) for r in rows], uid


def main():
    p = platforms.get(PLATFORM)
    if not p:
        log("未知平台：%s" % PLATFORM)
        return 1
    if not p.get("chat_url"):
        log("该平台未配置 chat_url")
        return 1
    if not session.can_search(PLATFORM):
        log("该平台没有可用登录态，请先在应用第②阶段扫码登录")
        return 1

    tasks, uid = tasks_for_latest_user()
    log("平台=%s 用户=#%s 任务=%d" % (PLATFORM, uid, len(tasks)))
    page = session._get_page(PLATFORM, hidden=True)
    log("浏览器就绪")

    info = {}
    dom_items = []
    packets = []
    try:
        page.listen.start()
        from urllib.parse import urlsplit
        home = p.get("chat_home_url") or ""
        if not home:
            parts = urlsplit(p.get("login_url", "") or "")
            if parts.scheme and parts.netloc:
                home = "%s://%s/" % (parts.scheme, parts.netloc)
        if home:
            page.get(home)
            page.wait(3)
        clicked = page.run_js("""
            const a = Array.from(document.querySelectorAll('a')).find(function (x) {
                return (x.innerText || '').trim() === '消息'
                    || (x.getAttribute('href') || '').indexOf('/web/chat') >= 0
                    || (x.getAttribute('href') || '').indexOf('/im') >= 0;
            });
            if (a) { a.click(); return a.getAttribute('href') || 'clicked'; }
            return '';
        """)
        log("点击消息入口：%r" % clicked)
        if not clicked:
            page.get(p["chat_url"])
        page.wait(int(getattr(config, "CHAT_LOAD_WAIT", 12)))
        info["url"] = page.url
        info["title"] = page.title
        info["body"] = (page.run_js("return (document.body && document.body.innerText || '').slice(0,3000);") or "")
        info["class_inventory"] = page.run_js("""
            const m = {};
            document.querySelectorAll('[class]').forEach(function (el) {
                String(el.className || '').split(/\\s+/).forEach(function (k) {
                    if (k && (k.indexOf('chat') >= 0 || k.indexOf('conversation') >= 0
                              || k.indexOf('message') >= 0 || k.indexOf('im-') >= 0
                              || k.indexOf('session') >= 0)) {
                        m[k] = (m[k] || 0) + 1;
                    }
                });
            });
            return m;
        """)
        dom_items = page.run_js("""
            const out = [];
            document.querySelectorAll('[class*=chat-item], [class*=session], [class*=conversation], li')
              .forEach(function (el) {
                  const t = (el.innerText || '').trim().replace(/\\s+/g, ' ');
                  if (t && t.length > 2) out.push(t.slice(0, 300));
              });
            return out.slice(0, 60);
        """) or []
        # 抓最近的请求 URL
        for _ in range(12):
            try:
                pk = page.listen.wait(count=1, timeout=2, fit_count=False)
            except Exception:
                break
            if pk in (False, None):
                continue
            url = ""
            for path in (("url",), ("request", "url")):
                cur = pk
                try:
                    for attr in path:
                        cur = getattr(cur, attr)
                    if isinstance(cur, str):
                        url = cur
                        break
                except Exception:
                    continue
            if url:
                packets.append(url)
    finally:
        try:
            page.listen.stop()
        except Exception:
            pass
        try:
            session.dpage_quit(PLATFORM)
        except Exception:
            pass

    records = replies.records_from_dom(dom_items, tasks)
    payload = {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "platform": PLATFORM,
        "page": info,
        "request_urls": packets,
        "dom_items": dom_items[:60],
        "parsed": {"records": records, "candidates": replies.match_tasks(records, tasks)},
    }
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    log("URL: %s" % info.get("url"))
    log("标题: %s" % info.get("title"))
    log("DOM 条目: %d | 请求: %d | 解析会话: %d | 匹配任务: %d"
        % (len(dom_items), len(packets), len(records), len(payload["parsed"]["candidates"])))
    log("样本已保存：%s" % OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
