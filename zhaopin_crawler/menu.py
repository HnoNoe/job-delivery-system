# -*- coding: utf-8 -*-
"""
menu.py —— 图形化菜单（双击 启动.bat 时调用）
==============================================
批处理对中文编码很敏感，所以中文菜单放在 Python 里，避免乱码。

也可以带参数直接跑：
    python menu.py check    环境自检
    python menu.py crawl    正式采集
    python menu.py demo     演示模式
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

MENU = """
====================================================
        智联招聘 岗位采集 + 智能分类
====================================================
  1. 环境自检（第一次请先运行这个）
  2. 开始抓取岗位
  3. 演示模式（不联网，先看效果）
  4. 打开输出文件夹
  5. 安装依赖
  0. 退出
===================================================="""


def setup_console():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def clear():
    if os.name == "nt":
        os.system("cls")


def pause():
    if os.environ.get("NO_PAUSE"):
        return
    try:
        input("\n按回车键返回菜单...")
    except (EOFError, KeyboardInterrupt):
        pass


def run(args):
    return subprocess.call([sys.executable, *args], cwd=str(ROOT))


def do_check():
    print(">>> 环境自检\n")
    run(["check_env.py"])


def do_crawl():
    print(">>> 开始抓取")
    print("提示：会弹出一个浏览器窗口自动翻页抓取，抓完自动生成 Excel。不需要登录。\n")
    run(["main.py", "--open"])


def do_demo():
    print(">>> 演示模式：不访问网站，用示例数据跑通【分类 -> 统计 -> 导出 Excel】\n")
    run(["main.py", "--demo", "--open"])


def do_deps():
    print(">>> 安装依赖（pip install -r requirements.txt）\n")
    run(["-m", "pip", "install", "-r", "requirements.txt"])


def do_open():
    out = ROOT / "output"
    if out.exists():
        try:
            os.startfile(str(out))  # noqa: S606
        except Exception as e:  # noqa: BLE001
            print(f"打开文件夹失败：{e}")
    else:
        print("还没有输出文件，请先运行 2 或 3。")


ACTIONS = {
    "1": ("环境自检", do_check),
    "2": ("开始抓取", do_crawl),
    "3": ("演示模式", do_demo),
    "4": ("打开输出文件夹", do_open),
    "5": ("安装依赖", do_deps),
}
SHORTCUTS = {"check": do_check, "crawl": do_crawl, "demo": do_demo,
             "deps": do_deps, "open": do_open}


def main():
    setup_console()
    if len(sys.argv) > 1:
        fn = SHORTCUTS.get(sys.argv[1].lower())
        if fn:
            fn()
            return 0
        print(f"未知参数：{sys.argv[1]}")
        return 1

    while True:
        clear()
        print(MENU)
        try:
            choice = input("请输入序号后回车：").strip()
        except (EOFError, KeyboardInterrupt):
            return 0
        if choice in ("0", "q", "quit", "exit"):
            return 0
        action = ACTIONS.get(choice)
        if not action:
            continue
        name, fn = action
        print(f"\n>>> {name}\n")
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            print(f"\n执行出错：{e}")
        pause()


if __name__ == "__main__":
    sys.exit(main())
