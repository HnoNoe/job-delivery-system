"""Create/repair a local virtual environment and install declared dependencies."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import venv

BASE = Path(__file__).resolve().parent


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser', action='store_true', help='安装平台登录/动态采集/填表依赖')
    parser.add_argument('--crawler', action='store_true', help='安装独立智联采集器依赖')
    args = parser.parse_args(argv)
    if sys.version_info < (3, 10):
        print('请安装 Python 3.10 或更高版本（推荐 3.11–3.13）。')
        return 1
    root = BASE / '.venv'
    python = root / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
    # Re-running venv updates a moved environment's interpreter/pyvenv.cfg.
    try:
        if Path(sys.prefix).resolve() == root.resolve():
            if not python.is_file():
                raise RuntimeError('请使用系统 Python 运行 setup_env.py 修复虚拟环境')
        else:
            healthy = False
            if python.is_file():
                probe = subprocess.run([str(python), '-c', 'import json,sys; print(json.dumps(sys.prefix))'],
                                       capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=15)
                if probe.returncode == 0:
                    healthy = Path(json.loads(probe.stdout.strip())).resolve() == root.resolve()
            if not healthy:
                venv.EnvBuilder(with_pip=True).create(root)
        packages = [BASE / 'requirements.txt']
        if args.browser:
            packages.append(BASE / 'requirements-browser.txt')
        if args.crawler:
            packages.append(BASE / 'zhaopin_crawler' / 'requirements.txt')
        command = [str(python), '-m', 'pip', 'install']
        for package in packages:
            command.extend(['-r', str(package)])
        subprocess.run(command, cwd=str(BASE), check=True)
        subprocess.run([str(python), '-m', 'pip', 'check'], check=True)
        print('安装完成。启动：python start.py')
        return 0
    except (OSError, subprocess.SubprocessError, RuntimeError, ValueError) as exc:
        print('安装失败：%s' % exc)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
