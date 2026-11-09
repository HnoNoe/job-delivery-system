"""单文件便携版入口。

双击 exe 即启动内置 Streamlit 仪表盘：
- 所有 Python 依赖、前端静态资源、app.py 都打进 exe，目标机器无需安装 Python；
- 运行数据（数据库 / 简历 / 材料包 / 登录态 / 日志）默认写在 exe 同目录，
  目录不可写时回退到 %LOCALAPPDATA%\\JobDeliverySystem；
- 端口默认 8501，被占用时自动换空闲端口，并打印实际地址；
- 首次运行会自动打开浏览器；也可用 --no-browser 关闭。

仍然是 Streamlit + 本地浏览器自动化：真实平台登录/检索需要目标机器装有
Chrome / Edge（Windows 自带 Edge 即可）。
"""
import os
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path

APP_NAME = "求职批量投递系统"


def bundle_dir() -> Path:
    """打包后的资源目录（onefile 解压目录 / 源码目录）。"""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def exe_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_probe"
        probe.write_text("1", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def runtime_home() -> Path:
    """运行数据目录：优先 exe 同目录（便携），不可写时回退用户目录。"""
    env = os.environ.get("JOBDELIVERY_HOME")
    if env:
        return Path(env).expanduser().resolve()
    portable = exe_dir()
    if _writable(portable):
        return portable
    fallback = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "JobDeliverySystem"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def free_port(preferred: int) -> int:
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]


def wait_and_open(port: int, timeout: float = 90.0) -> None:
    """等服务就绪后再开浏览器，避免打开“无法访问”。"""
    deadline = time.time() + timeout
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    url = "http://127.0.0.1:%d/_stcore/health" % port
    while time.time() < deadline:
        try:
            with opener.open(url, timeout=1) as resp:
                if resp.status == 200 and resp.read().strip() == b"ok":
                    import webbrowser
                    webbrowser.open("http://127.0.0.1:%d" % port)
                    return
        except OSError:
            pass
        time.sleep(0.5)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

    app = bundle_dir() / "app.py"
    if not app.is_file():
        print("❌ 找不到内置应用文件：%s" % app)
        return 1

    home = runtime_home()
    os.environ["JOBDELIVERY_HOME"] = str(home)
    os.environ.setdefault("JOBDELIVERY_DB", str(home / "data" / "jobdelivery.db"))

    port = free_port(int(os.environ.get("JOBDELIVERY_PORT", "8501")))
    url = "http://127.0.0.1:%d" % port

    print("=" * 56)
    print("  %s · 便携版" % APP_NAME)
    print("=" * 56)
    print("运行目录：%s" % home)
    print("访问地址：%s" % url)
    print("首次启动需要十几秒解压/加载，请稍候……")

    if "--check" in argv:
        import importlib
        for name in ("streamlit", "plotly", "pandas", "numpy", "reportlab", "pdfplumber",
                     "DrissionPage", "selenium"):
            try:
                mod = importlib.import_module(name)
                print("  %-14s %s" % (name, getattr(mod, "__version__", "ok")))
            except Exception as exc:
                print("  %-14s 缺失：%s" % (name, exc))
        try:
            from browser_runtime import find_browser
            print("  %-14s %s" % ("浏览器", find_browser()[0]))
        except Exception as exc:
            print("  %-14s 未找到：%s" % ("浏览器", exc))
        return 0

    if "--no-browser" not in argv:
        threading.Thread(target=wait_and_open, args=(port,), daemon=True).start()

    from streamlit.web import cli as stcli

    sys.argv = [
        "streamlit", "run", str(app),
        # 打包后 Streamlit 会被判定为 developmentMode，从而禁止指定端口，必须显式关掉
        "--global.developmentMode=false",
        "--server.headless=true",
        "--server.port=%d" % port,
        "--server.address=127.0.0.1",
        "--server.fileWatcherType=none",
        "--browser.gatherUsageStats=false",
        "--theme.base=light",
        "--theme.primaryColor=#4F46E5",
    ]
    return stcli.main()


if __name__ == "__main__":
    raise SystemExit(main())
