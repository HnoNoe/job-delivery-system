"""账号体系：注册 / 登录 / 会话保持。

安全设计：
- 库中只存 加盐 PBKDF2-HMAC-SHA256 哈希（10 轮迭代），永不存明文密码；
- 会话凭证 = 用户名 + 哈希前 32 位派生的校验符，存本地 session.json，
  启动时回库比对，凭证泄露也无法反推密码；
- 用户名规范化（去空白、限长、禁特殊字符），同名账号全局唯一。
"""
import hashlib
import json
import os
import re
import secrets

import config
import db

_PBKDF2_ROUNDS = 100_000
_SESSION_PATH = lambda: os.path.join(config.DATA_DIR, "session.json")  # noqa: E731

_USERNAME_RE = re.compile(r"^[\w\u4e00-\u9fff-]{2,32}$")


def _norm_username(username):
    return (username or "").strip()


def valid_username(username):
    return bool(_USERNAME_RE.match(_norm_username(username)))


def hash_password(password, salt_hex):
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                             bytes.fromhex(salt_hex), _PBKDF2_ROUNDS)
    return dk.hex()


def register(username, password):
    """注册。返回 (ok, message)。"""
    username = _norm_username(username)
    if not valid_username(username):
        return False, "用户名需 2~32 位（中文/字母/数字/下划线/连字符）"
    if not password or len(password) < 6:
        return False, "密码至少 6 位"
    salt = secrets.token_hex(16)
    pw_hash = hash_password(password, salt)
    with db.use_cloud():
        conn = db.get_conn()
        try:
            n = conn.execute(
                "SELECT COUNT(*) FROM accounts WHERE username = ?", (username,)).fetchone()[0]
            if n:
                return False, "用户名已被注册"
            conn.execute(
                "INSERT INTO accounts (username, pw_hash, salt) VALUES (?, ?, ?)",
                (username, pw_hash, salt))
            conn.commit()
        finally:
            conn.close()
    _save_session(username, pw_hash)
    return True, "注册成功"


def login(username, password):
    """登录。返回 (ok, message)。"""
    username = _norm_username(username)
    with db.use_cloud():
        row = db.get_conn().execute(
            "SELECT pw_hash, salt FROM accounts WHERE username = ?", (username,)).fetchone()
    if row is None:
        return False, "账号不存在"
    pw_hash = row["pw_hash"] if isinstance(row, dict) else row[0]
    salt = row["salt"] if isinstance(row, dict) else row[1]
    if secrets.compare_digest(hash_password(password, salt), pw_hash):
        _save_session(username, pw_hash)
        return True, "登录成功"
    return False, "密码错误"


def logout():
    try:
        os.remove(_SESSION_PATH())
    except OSError:
        pass


def current_user():
    """当前登录用户；未登录或会话失效返回 None。"""
    try:
        with open(_SESSION_PATH(), encoding="utf-8") as f:
            sess = json.load(f)
    except (OSError, ValueError):
        return None
    username = sess.get("username", "")
    verifier = sess.get("verifier", "")
    if not username or not verifier:
        return None
    with db.use_cloud():
        row = db.get_conn().execute(
            "SELECT pw_hash FROM accounts WHERE username = ?", (username,)).fetchone()
    if row is None:
        return None
    pw_hash = row["pw_hash"] if isinstance(row, dict) else row[0]
    return username if secrets.compare_digest(pw_hash[:32], verifier) else None


def _save_session(username, pw_hash):
    os.makedirs(config.DATA_DIR, exist_ok=True)
    tmp = _SESSION_PATH() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"username": username, "verifier": pw_hash[:32]}, f)
    os.replace(tmp, _SESSION_PATH())
