"""复现并验证修复：全新隔离环境（零表）下启动桌面端，main() 必须自建本地表。"""
import os
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
os.environ["JOBDELIVERY_GUI_TEST"] = "1"

from test_support import isolate_test_environment
isolate_test_environment()

import tkinter as tk
_failed = []
tk.Tk._orig_rce = tk.Tk.report_callback_exception
def _rce(self, exc, val, tb):
    _failed.append("%s: %s" % (exc.__name__, val))
    tk.Tk._orig_rce(self, exc, val, tb)
tk.Tk.report_callback_exception = _rce

import auth, mydata
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

import db
conn = db.get_conn()
tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
conn.close()
need = {"user_records", "experience_items", "jobs", "delivery_tasks"}
missing = need - tables
assert not missing, "本地库缺表：%s（desktop.main 未建表）" % missing
print("=== 桌面端全新环境建表冒烟通过 ===")
