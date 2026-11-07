"""Portable filenames and resolution of paths saved before moving the project."""
import re
from pathlib import Path, PureWindowsPath

import config


def safe_filename(value, limit=80):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value or "未命名"))
    name = name.strip(" .")[:limit].rstrip(" .") or "未命名"
    if name.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *[f"{p}{n}" for p in ("COM", "LPT") for n in range(1, 10)]}:
        name = "_" + name
    return name


def resolve_resume(value):
    if not value:
        return None
    path = Path(value)
    # Always prefer the copied artifact in the current runtime directory.
    name = PureWindowsPath(str(value)).name
    local = config.RUNTIME_DIR / "resumes" / name
    if local.is_file():
        return local
    if not path.is_absolute():
        path = config.RUNTIME_DIR / path
    return path if path.is_file() else None
