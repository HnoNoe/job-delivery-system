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
# 自定义 Streamlit 组件（第⑤步分析工作台、画像广场联动投影台，原生 HTML/CSS/SVG）
datas.append((os.path.join("components", "match_space"), os.path.join("components", "match_space")))
datas.append((os.path.join("components", "profile_plaza"), os.path.join("components", "profile_plaza")))

LOCAL_MODULES = [
    "config", "db", "schema", "formulas", "embedding", "user_profile", "recommend",
    "matching", "tasks", "verification", "generation", "delivery", "feedback",
    "pipeline", "loop", "platforms", "session", "crawler", "form_filler", "llm",
    "logging_setup", "theme", "viz", "login_status", "runtime_paths", "browser_runtime",
    "persona", "workbench", "profile_plaza",
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
    excludes=["tests", "pytest", "matplotlib", "tkinter",
              # PIL.ImageQt 等会把 Qt 绑定误拖进依赖图，分析 Qt DLL 极慢且可能卡死；本应用不用 Qt
              "PyQt5", "PyQt6", "PySide2", "PySide6",
              # 便携版不内置深度学习栈（未装 sentence-transformers 时应用自动回退哈希嵌入），
              # 否则 torch 数 GB 二进制会让打包体积与时间爆炸
              "torch", "torchaudio", "torchvision", "transformers", "sentence_transformers",
              # 科学计算重包在本项目无引用（pandas 的可选加速链会误拖入）
              "numba", "llvmlite", "scipy", "sklearn",
              # altair/narwhals 的可选后端与图像处理链，本项目无引用，单 polars 就有 150MB+
              "polars", "cv2"],
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
