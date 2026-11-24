"""CLI 入口 —— 裁剪后的最小系统：只保留 登录 / 检索岗位 / 投递。

用法：
  python main.py login <platform>            用你自己的浏览器打开登录页（手动登录）
  python main.py grab <platform>             从本机浏览器读出登录态存盘（登录完成后执行；
                                             Edge/Chrome 新版加密需以管理员身份运行本程序）
  python main.py search <platform> <关键词> [--pages N]   检索并入岗位库
  python main.py maketasks                   把岗位库里的在架岗位建成投递任务（去重）
  python main.py deliver [--limit N]         批量投递待投递任务（安全模式默认只准备材料）
  python main.py status                      看登录态/岗位/任务统计
"""
import argparse
import json
import sys


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(prog="jobdelivery", description="求职批量投递（检索+投递最小系统）")
    sub = p.add_subparsers(dest="cmd")

    lg = sub.add_parser("login", help="用你自己的浏览器打开平台登录页")
    lg.add_argument("platform")

    gr = sub.add_parser("grab", help="从本机浏览器读取登录态存盘")
    gr.add_argument("platform")

    se = sub.add_parser("search", help="检索岗位并入库")
    se.add_argument("platform")
    se.add_argument("keyword")
    se.add_argument("--pages", type=int, default=2)
    se.add_argument("--city", default="")

    sub.add_parser("maketasks", help="岗位库 → 投递任务（去重）")

    bt = sub.add_parser("deliver", help="批量投递待投递任务")
    bt.add_argument("--limit", type=int, default=0)
    bt.add_argument("--all", action="store_true", help="投全部待投递（仍受每日上限约束）")

    sub.add_parser("status", help="登录态/岗位/任务统计")

    a = p.parse_args(argv)

    if a.cmd == "login":
        import grab_login
        ok, msg = grab_login.open_in_user_browser(a.platform)
        print(("✅ " if ok else "❌ ") + msg)
        return 0 if ok else 1

    if a.cmd == "grab":
        from urllib.parse import urlparse
        import grab_login
        import platforms as plats
        import session
        host = urlparse((plats.get(a.platform) or {}).get("login_url", "")).hostname or ""
        domain = ".".join(host.split(".")[-2:]) if host else ""
        cookies, err = grab_login.grab_cookies(domain)
        if not cookies:
            hint = "" if grab_login.is_admin() else \
                "\n提示：Edge/Chrome 新版加密需要管理员权限——请右键→以管理员身份运行本程序再执行 grab。"
            print("❌ 读取失败：%s%s" % (err, hint))
            return 1
        n = session.save_cookies(a.platform, cookies)
        print("✅ 已保存 %d 个 cookie（平台：%s）" % (n, a.platform))
        return 0

    if a.cmd == "search":
        import jobstore
        import loop
        import session
        if not session.can_search(a.platform):
            print("❌ %s 没有可用登录态，请先 login + grab。" % a.platform)
            return 1
        jobs, logs = loop.search_logged_in_platforms([a.platform], a.keyword,
                                                     city=a.city, pages=a.pages)
        for k, msg in logs:
            print("  [%s] %s" % (k, msg))
        n = jobstore.store_jobs(jobs, user_id=1)
        print("✅ 入库 %d 个岗位（检索到 %d 条）。" % (n, len(jobs)))
        print("下一步：python main.py maketasks")
        return 0

    if a.cmd == "maketasks":
        import db
        import delivery
        created = 0
        with db.get_conn() as conn:
            rows = conn.execute(
                "SELECT job_id, fields FROM jobs WHERE active=1 ORDER BY job_id").fetchall()
            for r in rows:
                f = json.loads(r["fields"])
                exists = conn.execute(
                    "SELECT 1 FROM delivery_tasks WHERE job_id=? AND user_id=1",
                    (r["job_id"],)).fetchone()
                if exists:
                    continue
                entry_type, entry_addr = delivery.classify_entry(
                    f.get("投递入口类型", ""), f.get("投递入口地址", "")) \
                    if False else (f.get("投递入口类型", ""), f.get("投递入口地址", ""))
                conn.execute(
                    "INSERT INTO delivery_tasks (job_id, user_id, job_name, unit_name, job_link,"
                    " entry_type, entry_addr, status) VALUES (?,?,?,?,?,?,?,'待投递')",
                    (r["job_id"], 1, f.get("岗位名称", ""), f.get("单位名称", ""),
                     f.get("岗位链接", ""), entry_type, entry_addr))
                created += 1
            conn.commit()
        print("✅ 新建 %d 个投递任务（已存在的自动跳过）。" % created)
        return 0

    if a.cmd == "deliver":
        import delivery
        res = delivery.deliver_batch(limit=a.limit or None, all_pending=a.all)
        print(json.dumps({k: v for k, v in res.items() if k != "明细"},
                         ensure_ascii=False, indent=2))
        for task_id, ok, msg in res.get("明细", []):
            print("  任务%s：%s %s" % (task_id, "✅" if ok else "❌", msg))
        return 0

    if a.cmd == "status":
        import login_status
        import session
        import db
        for st in login_status.check_all(online=False):
            print("  登录态 %-8s %s %s" % (st["key"], st["state"], st.get("detail", "")))
        with db.get_conn() as conn:
            nj = conn.execute("SELECT COUNT(*) c FROM jobs WHERE active=1").fetchone()["c"]
            nt = conn.execute("SELECT COUNT(*) c FROM delivery_tasks").fetchone()["c"]
            np_ = conn.execute(
                "SELECT COUNT(*) c FROM delivery_tasks WHERE status='待投递'").fetchone()["c"]
            nd = conn.execute(
                "SELECT COUNT(*) c FROM delivery_tasks WHERE status='已投递'").fetchone()["c"]
        print("  岗位库在架 %d；任务 %d（待投递 %d / 已投递 %d）" % (nj, nt, np_, nd))
        return 0

    p.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
