"""注册 / 登录 / 登出。"""
import secrets

from fastapi import APIRouter, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse

import db
from auth import hash_password, valid_username, _norm_username  # noqa
from server import security
from server.templating import render

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return render(request, "login.html", {"error": "", "mode": "login"})


@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return render(request, "login.html", {"error": "", "mode": "register"})


@router.post("/register")
def register(request: Request, username: str = Form(...), password: str = Form(...),
             password2: str = Form(...)):
    if not security.same_origin(request):
        raise HTTPException(400, "非法请求来源")
    u = _norm_username(username)
    if not valid_username(u):
        return render(request, "login.html", {"error": "用户名需 2~32 位（中文/字母/数字/下划线/连字符）", "mode": "register"})
    if len(password) < 6:
        return render(request, "login.html", {"error": "密码至少 6 位", "mode": "register"})
    if password != password2:
        return render(request, "login.html", {"error": "两次输入的密码不一致", "mode": "register"})
    salt = secrets.token_hex(16)
    pw_hash = hash_password(password, salt)
    with db.use_cloud():
        conn = db.get_conn()
        conn.execute("DELETE FROM web_sessions WHERE expires_at < NOW()")
        exists = conn.execute("SELECT 1 FROM accounts WHERE username=?", (u,)).fetchone()
        if exists:
            conn.close()
            return render(request, "login.html", {"error": "账号已存在，直接登录", "mode": "register"})
        n = conn.execute("SELECT COUNT(*) AS c FROM accounts").fetchone()
        n = n["c"] if isinstance(n, dict) else n[0]
        conn.execute(
            "INSERT INTO accounts (username, pw_hash, salt, is_admin, status) VALUES (?,?,?,?, 'active')",
            (u, pw_hash, salt, 1 if n == 0 else 0))  # 首个注册账号即管理员（bootstrap）
        conn.commit()
        conn.close()
    if n == 0:
        security.audit(u, "bootstrap_admin", u, "首个注册账号自动成为管理员")
    token = security.issue_session(u, request.client.host if request.client else "")
    resp = RedirectResponse("/app", status_code=status.HTTP_303_SEE_OTHER)
    resp.set_cookie(security.SESSION_COOKIE, token, max_age=7 * 86400,
                    httponly=True, samesite="lax")
    return resp


@router.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    if not security.same_origin(request):
        raise HTTPException(400, "非法请求来源")
    u = _norm_username(username)
    ip = request.client.host if request.client else ""
    allowed, wait = security.check_rate_limit(u, ip)
    if not allowed:
        return render(request, "login.html",
                      {"error": "失败次数过多，请 %d 分钟后再试" % max(1, wait // 60), "mode": "login"})
    ok = False
    with db.use_cloud():
        conn = db.get_conn()
        row = conn.execute("SELECT pw_hash, salt, status FROM accounts WHERE username=?", (u,)).fetchone()
        conn.close()
    if row is not None:
        pw_hash = row["pw_hash"] if isinstance(row, dict) else row[0]
        salt = row["salt"] if isinstance(row, dict) else row[1]
        st = row["status"] if isinstance(row, dict) else row[2]
        import hmac as _hmac
        ok = _hmac.compare_digest(hash_password(password, salt), pw_hash) and st == "active"
    if not ok:
        security.record_fail(u, ip)
        return render(request, "login.html", {"error": "账号不存在、密码错误或已禁用", "mode": "login"})
    security.clear_fails(u, ip)
    token = security.issue_session(u, ip)
    resp = RedirectResponse("/app", status_code=status.HTTP_303_SEE_OTHER)
    resp.set_cookie(security.SESSION_COOKIE, token, max_age=7 * 86400,
                    httponly=True, samesite="lax")
    return resp


@router.get("/logout")
def logout(request: Request):
    token = request.cookies.get(security.SESSION_COOKIE, "")
    if token:
        security.revoke_session(token)
    resp = RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    resp.delete_cookie(security.SESSION_COOKIE)
    return resp
