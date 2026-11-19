"""清空本机数据（对应侧栏「🧹 清空本机数据」）。

只清理**本机这份程序**产生的数据，不触碰系统里其它东西：
- 数据库业务表（用户/经历/权重/岗位/任务/反馈/画像/回应/收件箱/自动检查状态）；
- 生成的文件（resumes/、packages/、outbox/）；
- 运行产物（send_count、mock 记录、chat_probe、search_debug 日志）；
- 可选：平台登录态（sessions/ 下的 cookie 与浏览器 profile，清掉后需重新扫码）。

保留：数据库表结构、data/ui_prefs.json（主题偏好）、代码与配置。
"""
import shutil
from pathlib import Path

import config

# 业务表（保留表结构，只删数据）
TABLES = (
    "user_records", "experience_items", "profile_weights",
    "jobs", "user_jobs", "user_job_scopes", "target_jobs",
    "delivery_tasks", "job_field_map", "task_indicators", "delivery_attempts",
    "history_samples", "job_centers", "profile_pool",
    "hr_responses", "hr_inbox", "app_state",
)

# 生成/运行产物（可安全删除）
RUNTIME_FILES = (
    "send_count.txt",
    "mock_greets.jsonl",
    "mock_replies.jsonl",
)


def _data_dir():
    return Path(config.DATA_DIR)


def _runtime_dir():
    return Path(config.RUNTIME_DIR)


def clear_database():
    """清空业务表数据，返回每张表删除的行数。"""
    import db
    db.init_db()
    removed = {}
    with db.get_conn() as conn:
        for table in TABLES:
            try:
                cur = conn.execute("DELETE FROM %s" % table)
                removed[table] = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
            except Exception:
                removed[table] = 0
        try:
            conn.execute("DELETE FROM sqlite_sequence")
        except Exception:
            pass
    return removed


def clear_files():
    """删除生成的简历/材料包/发件箱与运行产物，返回删除项列表。"""
    removed = []
    with __import__("contextlib").suppress(Exception):
        for name in ("resumes", "packages", "outbox"):
            path = _runtime_dir() / name
            if path.exists():
                shutil.rmtree(path, ignore_errors=True)
                path.mkdir(parents=True, exist_ok=True)
                removed.append(name + "/")
    data = _data_dir()
    if data.exists():
        for name in RUNTIME_FILES:
            p = data / name
            if p.exists():
                try:
                    p.unlink()
                    removed.append("data/" + name)
                except OSError:
                    pass
        for pattern in ("chat_probe_*.json", "search_debug_*.log"):
            for p in data.glob(pattern):
                try:
                    p.unlink()
                    removed.append("data/" + p.name)
                except OSError:
                    pass
    return removed


def clear_login_state():
    """退出所有平台并删除登录态目录（cookie + 浏览器 profile）。"""
    removed = []
    try:
        import platforms
        import session
        for pk in platforms.PLATFORMS:
            try:
                session.clear_session(pk)
            except Exception:
                pass
            try:
                session.dpage_quit(pk)
            except Exception:
                pass
    except Exception:
        pass
    sessions = _runtime_dir() / "sessions"
    if sessions.exists():
        for child in sessions.iterdir():
            try:
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink()
                removed.append("sessions/" + child.name)
            except OSError:
                pass
    return removed


def reset_all(clear_login=False):
    """执行完整清理，返回摘要 dict（供界面展示/日志）。"""
    summary = {"database": {}, "files": [], "login": [], "clear_login": bool(clear_login)}
    summary["database"] = clear_database()
    summary["files"] = clear_files()
    if clear_login:
        summary["login"] = clear_login_state()
    return summary
