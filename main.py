"""CLI 入口。

用法：
  python main.py web                  启动 Web Dashboard
  python main.py login <platform>     扫码登录某平台（boss/zhilian/lagou/liepin/job51）
  python main.py search <platform> <关键词>  用登录态检索
  python main.py batch [--limit N]    批量投递待投递任务（Boss直聘，需先登录+生成任务）
"""
import argparse
import json
import sys


def main():
    p = argparse.ArgumentParser(prog="jobdelivery", description="求职批量投递系统")
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("web", help="启动 Web Dashboard")

    lg = sub.add_parser("login", help="扫码登录平台")
    lg.add_argument("platform")

    se = sub.add_parser("search", help="用登录态检索岗位")
    se.add_argument("platform")
    se.add_argument("keyword")

    bt = sub.add_parser("batch", help="批量投递待投递任务（Boss直聘）")
    bt.add_argument("--limit", type=int, default=None, help="最多投递条数（默认走单次批次上限）")

    args = p.parse_args()

    if args.cmd == "web":
        import subprocess
        subprocess.run([sys.executable, "-m", "streamlit", "run", "app.py"])
    elif args.cmd == "login":
        import session
        ok, msg = session.dpage_open(args.platform)
        print(msg)
        input("登录完成后按回车保存会话 ...")
        ok, msg = session.dpage_finish(args.platform)
        print(msg)
        session.dpage_quit(args.platform)
    elif args.cmd == "search":
        import session
        jobs = session.dpage_search(args.platform, args.keyword)
        print(json.dumps(jobs, ensure_ascii=False, indent=2))
        session.dpage_quit(args.platform)
    elif args.cmd == "batch":
        import config
        import delivery
        result = delivery.deliver_batch(limit=args.limit)
        print("批量投递结果：成功 %d / 失败 %d / 共 %d" % (result["成功数"], result["失败数"], result["投递数"]))
        if result["停止原因"]:
            print("停止原因：", result["停止原因"])
        for tid, ok, msg in result["明细"]:
            print("[%s] 任务%d: %s" % ("OK" if ok else "失败", tid, msg))
    else:
        p.print_help()


if __name__ == "__main__":
    main()

