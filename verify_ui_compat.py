"""前端渲染兼容性回归测试：消除 Streamlit 弃用报错，且跨版本可用。

Streamlit ≥1.49 弃用 `use_container_width`（2025-12-31 后移除），改用 `width='stretch'`；
但 requirements.txt 允许 `streamlit>=1.32`，因此 app.py 用 `_full_width_kwargs()` 版本自适应。

本测试离线运行（不联网、不起浏览器）校验四件事：
1. 静态：app.py（及其它模块）不再出现 `use_container_width=` 关键字实参；
2. 适配：helper 产出的参数名在当前 Streamlit 版本的 `st.dataframe` 签名里确实存在；
3. 动态：真实渲染不产生弃用日志，且对照探针能被检出（证明检测器不是假阴性）；
4. 集成：预置岗位数据后 app.py 无异常并渲染出表格。
"""
import ast
import inspect
import io
import logging
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import pandas as pd
import streamlit as st
from streamlit.testing.v1 import AppTest

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_PATH = os.path.join(BASE_DIR, "app.py")


def check(name, cond):
    print(("  PASS  " if cond else "  FAIL  ") + name)
    return bool(cond)


def legacy_call_sites(path):
    """返回文件中把 use_container_width 当关键字实参用的行号（应为空）。"""
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    return [n.lineno for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            for kw in n.keywords if kw.arg == "use_container_width"]


def load_helper():
    """取出 app.py 里真实的 `_full_width_kwargs` 函数体执行，避免整脚本副作用。"""
    with open(APP_PATH, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    node = next(n for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == "_full_width_kwargs")
    ns = {"st": st}
    exec(compile(ast.Module(body=[node], type_ignores=[]), APP_PATH, "exec"), ns)
    return ns["_full_width_kwargs"]


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())

    @property
    def deprecation_hits(self):
        # 去重：同一告警可能经 root/streamlit/deprecation_util 多个 logger 到达
        return sum(1 for m in set(self.messages) if "use_container_width" in m)


def run_app(target, seed_jobs=False):
    """执行目标脚本，返回 (异常列表, 表格数, 弃用告警条数)。"""
    cap = _Capture()
    # Streamlit 的弃用告警由 streamlit.deprecation_util 记录且不向 root 传播，
    # 所以同时挂到该 logger 与 root，避免漏检（假阴性）。
    loggers = [logging.getLogger(), logging.getLogger("streamlit.deprecation_util"),
               logging.getLogger("streamlit")]
    for lg in loggers:
        lg.addHandler(cap)
    try:
        at = AppTest.from_file(target)
        if seed_jobs:
            # 预置第③步检索结果，触发 app.py 中 show_table(...) 的渲染分支
            at.session_state["jobs"] = [
                {"岗位名称": "Python 后端开发", "单位名称": "示例科技", "城市": "北京",
                 "薪资": "15-25K", "学历": "本科", "经验": "1-3年", "行业": "互联网"},
                {"岗位名称": "后端工程师", "单位名称": "测试公司", "城市": "北京",
                 "薪资": "18-30K", "学历": "本科", "经验": "3-5年", "行业": "企业服务"},
            ]
        at.run(timeout=90)
        return ([str(e.value) for e in at.exception], len(at.dataframe), cap.deprecation_hits)
    finally:
        for lg in loggers:
            lg.removeHandler(cap)


ok = True

print("=== ① 静态检查：不再使用被弃用的参数 ===")
_legacy = legacy_call_sites(APP_PATH)
ok &= check("app.py 无 use_container_width= 调用（命中行号：%s）" % (_legacy or "无"), not _legacy)

print("=== ② 版本自适应：产出的参数名必须被当前版本支持 ===")
_kw = load_helper()()
_params = inspect.signature(st.dataframe).parameters
ok &= check("Streamlit %s 支持 %s" % (st.__version__, _kw), all(k in _params for k in _kw))
ok &= check("参数语义正确", _kw == ({"width": "stretch"} if tuple(
    int(x) for x in st.__version__.split(".")[:2]) >= (1, 49) else {"use_container_width": True}))

print("=== ③ 动态检查：对照探针 + 真实渲染 ===")
probe = os.path.join(tempfile.gettempdir(), "_verify_ui_compat_probe.py")
with open(probe, "w", encoding="utf-8") as f:
    f.write("import pandas as pd\nimport streamlit as st\n"
            "st.dataframe(pd.DataFrame({'a': [1]}), use_container_width=True, hide_index=True)\n")
try:
    _exc_p, _df_p, _hits_p = run_app(probe)
    ok &= check("对照探针可检出弃用告警（hits=%d，表格=%d）" % (_hits_p, _df_p),
                _hits_p > 0 and _df_p == 1)
finally:
    os.remove(probe)

_exc_a, _df_a, _hits_a = run_app(APP_PATH, seed_jobs=True)
ok &= check("app.py 端到端执行无异常（%s）" % (_exc_a or "无异常"), not _exc_a)
ok &= check("app.py 渲染出表格（表格=%d）" % _df_a, _df_a >= 1)
ok &= check("app.py 零弃用告警（hits=%d）" % _hits_a, _hits_a == 0)

print()
print("=== 前端渲染兼容性回归测试", "通过" if ok else "有失败", "===")
sys.exit(0 if ok else 1)
