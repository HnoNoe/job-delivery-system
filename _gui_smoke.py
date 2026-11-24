"""桌面端主界面构建冒烟：假装已登录，强制 show_main 构建全部四个页签。

任何页签构建异常都会被 tkinter 回调异常钩子捕获，结束后统一断言。
"""
import os
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
os.environ["JOBDELIVERY_GUI_TEST"] = "1"

import tkinter as tk

_failed = []
tk.Tk._orig_rce = tk.Tk.report_callback_exception
def _rce(self, exc, val, tb):
    _failed.append("%s: %s" % (exc.__name__, val))
    tk.Tk._orig_rce(self, exc, val, tb)
tk.Tk.report_callback_exception = _rce

import auth
import mydata
auth.current_user = lambda: "smoke"
auth.logout = lambda: None
mydata.pool_stats = lambda: {"accounts": 0, "jobs": 0}

import desktop
desktop.main()

if _failed:
    print("GUI 回调异常：")
    for f in _failed:
        print("  -", f)
    sys.exit(1)
print("=== 桌面端主界面（四页签）构建冒烟通过 ===")
