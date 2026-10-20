"""一键启动：自动启动 Web Dashboard，并打开浏览器。"""
import subprocess
import sys
import time
import socket
import webbrowser
from pathlib import Path

BASE = Path(__file__).resolve().parent


def port_open(port: int) -> bool:
    s = socket.socket()
    try:
        s.connect(("127.0.0.1", port))
        return True
    except Exception:
        return False
    finally:
        s.close()


def main():
    print("=" * 50)
    print("  求职批量投递系统 —— 一键启动")
    print("=" * 50)

    if port_open(8501):
        print("[1/2] Web Dashboard 已在运行 (端口 8501)")
    else:
        subprocess.Popen(
            [sys.executable, "-m", "streamlit", "run", "app.py",
             "--server.headless", "true", "--server.port", "8501"],
            cwd=str(BASE),
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        print("[1/2] 已启动 Web Dashboard (端口 8501)，等待就绪...")
        time.sleep(6)

    print("[2/2] 打开浏览器...")
    webbrowser.open("http://localhost:8501")
    print("完成！浏览器已打开，按页面步骤操作即可。")
    print("=" * 50)


if __name__ == "__main__":
    main()
