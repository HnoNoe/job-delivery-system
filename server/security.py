"""安全基元：服务端会话签发/校验、登录限流、审计、CSRF 同源校验。

密码哈希直接复用 auth.hash_password（PBKDF2，与桌面端同一套，账号全端通用）。
"""
import os
import secrets
import sys
import threading
import time
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db
from auth import hash_password  # noqa: F401  (复用 PBKDF2)

SESSION_COOKIE = "sid"
SESSION_DAYS = 7
_fail_lock = threading.Lock()
_fails = {}  # (username, ip) -> [timestamps]


def issue_session(owner, ip=""):
    """签发会话，返回 token。"""
    token = secrets.token_urlsafe(32)
    with db.use_cloud():
        conn = db.get_conn()
        conn.execute("DELETE FROM web_sessions WHERE expires_at < NOW()")
        conn.execute(
            "INSERT INTO web_sessions (token, owner, expires_at, ip) VALUES (?,?,DATE_ADD(NOW(), INTERVAL ? DAY),?)",
            (token, owner, SESSION_DAYS, ip))
        conn.commit()
        conn.close()
    return token


def revoke_session(token):
    with db.use_cloud():
        conn = db.get_conn()
        conn.execute("DELETE FROM web_sessions WHERE token=?", (token,))
        conn.commit()
        conn.close()


def owner_of_token(token):
    """有效 token → (owner, is_admin)；无效返回 (None, False)。"""
    if not token:
        return None, False
    with db.use_cloud():
        conn = db.get_conn()
        row = conn.execute(
            "SELECT s.owner, a.is_admin, a.status FROM web_sessions s "
            "JOIN accounts a ON a.username = s.owner "
            "WHERE s.token = ? AND s.expires_at > NOW()", (token,)).fetchone()
        conn.close()
    if row is None:
        return None, False
    status = row["status"] if isinstance(row, dict) else row[2]
    if status != "active":
        return None, False
    return (row["owner"] if isinstance(row, dict) else row[0]), \
           bool(row["is_admin"] if isinstance(row, dict) else row[1])


def check_rate_limit(username, ip):
    """登录限流：同一 账号+IP 10 分钟内最多失败 5 次。返回 (允许?, 剩余秒数)。"""
    key = (username, ip)
    now = time.time()
    with _fail_lock:
        ts = [t for t in _fails.get(key, []) if now - t < 600]
        _fails[key] = ts
        if len(ts) >= 5:
            return False, int(600 - (now - ts[0]))
    return True, 0


def record_fail(username, ip):
    with _fail_lock:
        _fails.setdefault((username, ip), []).append(time.time())


def clear_fails(username, ip):
    with _fail_lock:
        _fails.pop((username, ip), None)


def audit(actor, action, target="", detail=""):
    """治理动作全量记审计。"""
    with db.use_cloud():
        conn = db.get_conn()
        conn.execute("INSERT INTO audit_log (actor, action, target, detail) VALUES (?,?,?,?)",
                     (actor, action, str(target)[:128], str(detail)[:2000]))
        conn.commit()
        conn.close()


def same_origin(request):
    """表单 POST 的同源校验（Referer/Origin 必须指向本站）。"""
    host = request.headers.get("host", "")
    ref = request.headers.get("referer") or request.headers.get("origin") or ""
    return (not ref) or (host and host in ref)
