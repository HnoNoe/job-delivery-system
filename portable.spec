# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 规格：把 Streamlit 应用打成单文件便携版。

用法：
    set PORTABLE_ONEFILE=0 && pyinstaller portable.spec --noconfirm --clean   # 目录版（调试）
    set PORTABLE_ONEFILE=1 && pyinstaller portable.spec --noconfirm --clean   # 单文件版
"""
import os

from PyInstaller.utils.hooks import collect_all, copy_metadata

datas, binaries, hiddenimports = [], [], []

# 前端静态资源 / 字体 / 二进制都在包里，目标机器不需要装 Python 依赖
for pkg in ("streamlit", "altair", "plotly", "reportlab", "pdfplumber",
            "pypdfium2", "bs4", "DrissionPage", "selenium"):
    try:
        d, b, h = collect_all(pkg)
    except Exception:
        continue
    datas += d
    binaries += b
    hiddenimports += h

# Streamlit / pandas 等在运行时通过 importlib.metadata 读版本号，必须带上元数据
for pkg in ("streamlit", "altair", "pandas", "numpy", "plotly", "pyarrow", "packaging"):
    try:
        datas += copy_metadata(pkg)
    except Exception:
        pass

# 内置应用脚本：由 Streamlit 以脚本方式执行，所以作为数据文件带上
datas.append(("app.py", "."))

LOCAL_MODULES = [
    "config", "db", "schema", "formulas", "embedding", "user_profile", "recommend",
    "matching", "tasks", "verification", "generation", "delivery", "feedback",
    "pipeline", "loop", "platforms", "session", "crawler", "form_filler", "llm",
    "logging_setup", "theme", "viz", "login_status", "runtime_paths", "browser_runtime",
]
hiddenimports += LOCAL_MODULES
# Streamlit 1.66 起用 uvicorn/starlette 提供服务，这些是动态导入，显式声明
hiddenimports += ["uvicorn", "starlette", "anyio", "h11", "websockets",
                  "python_multipart", "watchdog", "tornado", "nest_asyncio"]

a = Analysis(
    ["portable_launcher.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tests", "pytest", "matplotlib", "tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)

ONEFILE = os.environ.get("PORTABLE_ONEFILE", "1") == "1"

if ONEFILE:
    exe = EXE(
        pyz, a.scripts, a.binaries, a.datas, [],
        name="JobDeliverySystem",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=True,
        disable_windowed_traceback=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
else:
    exe = EXE(
        pyz, a.scripts, [],
        exclude_binaries=True,
        name="JobDeliverySystem",
        debug=False,
        strip=False,
        upx=False,
        console=True,
    )
    coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="JobDeliverySystem")
