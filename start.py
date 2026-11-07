"""Cross-platform launcher with dependency checks and HTTP readiness probing."""
import argparse
import contextlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import build_opener, ProxyHandler
import webbrowser

BASE = Path(__file__).resolve().parent
PORT = 8501
URL = 'http://127.0.0.1:8501'
LOG_DIR = Path(os.environ.get('JOBDELIVERY_HOME', str(BASE))).expanduser().resolve() / 'logs'
REQUIRED = ('streamlit', 'numpy', 'pandas', 'plotly', 'reportlab', 'bs4', 'pdfplumber', 'requests')


def port_open(port=PORT, timeout=0.3):
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=timeout):
            return True
    except OSError:
        return False


def dependency_errors(python):
    probe = ('import importlib, json, sys\nerrors=[]\n'
             'for name in ' + repr(REQUIRED) + ':\n'
             ' try: importlib.import_module(name)\n'
             ' except Exception as e: errors.append(name + ": " + str(e))\n'
             'print(json.dumps(errors))\n')
    try:
        result = subprocess.run([str(python), '-c', probe], cwd=str(BASE), capture_output=True, text=True,
                                encoding='utf-8', errors='replace', timeout=45)
        if result.returncode:
            return [result.stderr.strip() or '解释器无法运行']
        return json.loads(result.stdout.strip().splitlines()[-1])
    except (OSError, subprocess.TimeoutExpired, ValueError, IndexError) as exc:
        return [str(exc)]


def has_streamlit(python):
    return not dependency_errors(python)


def find_python():
    candidates = [Path(sys.executable)] if sys.prefix != sys.base_prefix else []
    candidates += [BASE / '.venv' / 'Scripts' / 'python.exe', BASE / '.venv' / 'bin' / 'python', Path(sys.executable)]
    for candidate in dict.fromkeys(candidates):
        if candidate.is_file() and has_streamlit(candidate):
            return str(candidate)
    return None


def tail(path, n=20):
    try:
        return '\n'.join(path.read_text(encoding='utf-8', errors='replace').splitlines()[-n:])
    except OSError:
        return ''


def health_ready(port):
    try:
        opener = build_opener(ProxyHandler({}))
        with opener.open('http://127.0.0.1:%d/_stcore/health' % port, timeout=1) as response:
            return response.status == 200 and response.read().strip() == b'ok'
    except OSError:
        return False


def available_port(preferred):
    with socket.socket() as sock:
        try:
            sock.bind(('127.0.0.1', preferred))
        except OSError:
            sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description='求职批量投递系统')
    parser.add_argument('--port', type=int, default=PORT)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--foreground', action='store_true', help='前台运行，Ctrl+C 停止')
    parser.add_argument('--check', action='store_true', help='仅检查运行环境')
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error('端口须为 0 到 65535（0 表示自动选择）')
    print('求职批量投递系统')
    python = find_python()
    if python is None:
        print('运行环境不完整。请先执行：python setup_env.py')
        print('当前解释器：%s' % sys.executable)
        for problem in dependency_errors(sys.executable):
            print('  ' + problem)
        return 1
    print('Python: ' + python)
    if args.check:
        print('核心依赖检查通过。浏览器功能另需 python setup_env.py --browser。')
        return 0
    port = available_port(args.port)
    url = 'http://127.0.0.1:%d' % port
    if args.port and port != args.port:
        print('端口 %d 已占用，改用 %d。' % (args.port, port))
    cmd = [python, '-m', 'streamlit', 'run', str(BASE / 'app.py'), '--server.headless', 'true',
           '--server.port', str(port), '--server.address', '127.0.0.1', '--browser.gatherUsageStats', 'false']
    if args.foreground:
        print('启动：' + url)
        return subprocess.call(cmd, cwd=str(BASE))
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUTF8='1')
    with contextlib.ExitStack() as stack:
        out = stack.enter_context((LOG_DIR / 'streamlit.out.log').open('w', encoding='utf-8'))
        err = stack.enter_context((LOG_DIR / 'streamlit.err.log').open('w', encoding='utf-8'))
        proc = subprocess.Popen(cmd, cwd=str(BASE), stdout=out, stderr=err, stdin=subprocess.DEVNULL,
                                env=env, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    ready = False
    for _ in range(60):
        if proc.poll() is not None:
            break
        if health_ready(port):
            ready = True
            break
        time.sleep(0.5)
    if not ready:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        print('启动失败。日志：%s' % LOG_DIR)
        print(tail(LOG_DIR / 'streamlit.err.log') or tail(LOG_DIR / 'streamlit.out.log'))
        return 1
    (LOG_DIR / 'streamlit.pid').write_text(str(proc.pid), encoding='utf-8')
    (LOG_DIR / 'streamlit.json').write_text(json.dumps({'pid': proc.pid, 'url': url, 'app': str(BASE)}), encoding='utf-8')
    print('服务已就绪：%s （PID %d）' % (url, proc.pid))
    if not args.no_browser:
        try:
            if not webbrowser.open(url):
                print('请在浏览器中打开以上地址。')
        except webbrowser.Error:
            print('请在浏览器中打开以上地址。')
    print('前台运行并用 Ctrl+C 停止：python start.py --foreground')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
