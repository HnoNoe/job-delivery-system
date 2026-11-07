"""Locate installed Chromium browsers on Windows, macOS and Linux."""
import os
import shutil
from pathlib import Path

import config


def find_browser():
    if config.BROWSER_PATH:
        path = Path(config.BROWSER_PATH).expanduser()
        if not path.is_file():
            raise RuntimeError("JOBDELIVERY_BROWSER 指向的浏览器不存在：%s" % path)
        return str(path), "edge" if "msedge" in path.name.lower() else "chrome"
    candidates = []
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge", "msedge", "chrome"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))
    for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        root = os.environ.get(env)
        if root:
            candidates.extend(Path(root) / suffix for suffix in (
                "Google/Chrome/Application/chrome.exe", "Microsoft/Edge/Application/msedge.exe"))
    candidates.extend(Path(p) for p in (
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser"))
    for path in candidates:
        if path.is_file():
            return str(path), "edge" if "edge" in str(path).lower() else "chrome"
    raise RuntimeError("未找到 Chrome / Edge / Chromium。请安装浏览器，或用 JOBDELIVERY_BROWSER 指定可执行文件路径。")
