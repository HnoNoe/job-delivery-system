"""代码健康度回归测试：把体检发现的问题固化为护栏。

离线运行（不联网、不起浏览器），校验六件事：
1. schema 各字段列表内部无重复（字段名是统一字段数据库的基准）；
2. config 超参数落在合法域（式三~式五数学对象的前提 + 防封参数自洽）；
3. 全部业务模块可干净导入（无语法/循环导入/顶层副作用崩溃）；
4. app.py 无 st.rerun() 之后的不可达代码（「重新开始」按钮曾因此静默失效）；
5. 业务代码无 use_container_width= 调用（theme.py 是唯一适配层，豁免）；
6. db.init_db 后专利核心表全部存在。
"""
import ast
import pathlib
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = pathlib.Path(__file__).resolve().parent


def check(name, cond):
    print(("  PASS  " if cond else "  FAIL  ") + name)
    return bool(cond)


ok = True

print("=== ① schema：字段列表内部无重复 ===")
import schema
for lst_name in ("L0_FIELDS", "L1_TYPES", "L2_FIELDS", "L3_FIELDS",
                 "JOB_FIELDS", "TASK_FIELDS"):
    lst = getattr(schema, lst_name)
    ok &= check("%s 无重复字段" % lst_name, len(lst) == len(set(lst)))

print("=== ② config：超参数合法域 ===")
import config
ok &= check("式三权重非负且不同时为 0",
            config.W_S >= 0 and config.W_DELTA >= 0 and (config.W_S + config.W_DELTA) > 0)
ok &= check("式四 τ 严格为正", config.TAU > 0)
ok &= check("式五 η 严格为正", config.ETA > 0)
ok &= check("防封参数自洽（每日上限 ≥ 单次批次 ≥ 1，间隔 ≥ 0）",
            config.DAILY_SEND_LIMIT >= config.BATCH_SEND_LIMIT >= 1
            and config.DELIVER_INTERVAL >= 0)
ok &= check("SAFE_MODE 默认为开启", config.SAFE_MODE is True)

print("=== ③ 模块可干净导入 ===")
_MODULES = ["schema", "config", "db", "formulas", "embedding", "profile",
            "matching", "tasks", "verification", "recommend", "generation",
            "feedback", "delivery", "pipeline", "loop", "platforms", "session",
            "crawler", "form_filler", "llm", "logging_setup", "theme", "viz"]
_failed = []
for m in _MODULES:
    try:
        __import__(m)
    except Exception as e:
        _failed.append("%s(%s)" % (m, e))
ok &= check("全部 %d 个模块导入成功（失败：%s）" % (len(_MODULES), _failed or "无"),
            not _failed)

print("=== ④ app.py：st.rerun() 后无不可达代码 ===")


def _unreachable_after_rerun(path):
    """找出同一语句块内跟在 st.rerun() 后面的语句行号（rerun 会中断执行）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    hits = []

    def is_rerun(stmt):
        return (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)
                and isinstance(stmt.value.func, ast.Attribute)
                and stmt.value.func.attr == "rerun")

    def scan_body(body):
        for i, stmt in enumerate(body):
            if is_rerun(stmt) and i < len(body) - 1:
                hits.append(body[i + 1].lineno)
            for child in ast.iter_child_nodes(stmt):
                if isinstance(child, ast.stmt):
                    continue
            # 递归所有子语句块
            for field in ("body", "orelse", "finalbody"):
                sub = getattr(stmt, field, None)
                if isinstance(sub, list):
                    scan_body(sub)
            if isinstance(stmt, (ast.With, ast.AsyncWith)):
                pass
            if hasattr(stmt, "handlers"):  # try/except
                for h in stmt.handlers:
                    scan_body(h.body)

    scan_body(tree.body)
    return hits


_hits = _unreachable_after_rerun(BASE / "app.py")
ok &= check("st.rerun() 后无不可达语句（命中行号：%s）" % (_hits or "无"), not _hits)

print("=== ⑤ 业务代码无 use_container_width= 调用 ===")
_legacy = []
for f in sorted(BASE.glob("*.py")):
    if f.name == "theme.py":  # theme.chart 是唯一合法的版本适配层
        continue
    tree = ast.parse(f.read_text(encoding="utf-8"))
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            for kw in n.keywords:
                if kw.arg == "use_container_width":
                    _legacy.append("%s:%d" % (f.name, n.lineno))
ok &= check("无弃用调用（命中：%s）" % (_legacy or "无"), not _legacy)

print("=== ⑥ db.init_db 后核心表齐全 ===")
import db
db.init_db()
conn = db.get_conn()
_tables = {r[0] for r in conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
conn.close()
_NEED = {"user_records", "experience_items", "profile_weights", "jobs",
         "target_jobs", "delivery_tasks", "job_field_map", "task_indicators",
         "history_samples", "job_centers", "profile_pool"}
ok &= check("核心表齐全（缺失：%s）" % ((_NEED - _tables) or "无"), _NEED <= _tables)

print()
print("=== 代码健康度回归测试", "通过" if ok else "有失败", "===")
sys.exit(0 if ok else 1)
