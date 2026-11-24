"""管理端：总览 / 账号治理 / 内容治理 / 审计 / 系统。"""
import json
import secrets

import db
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import mydata
from auth import hash_password
from server import security
from server.deps import require_admin
from server.templating import render

router = APIRouter(prefix="/admin", tags=["admin"])

def _form(request: Request):
    import asyncio
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
    return loop.run_until_complete(request.form())




def _rows(rs):
    out = []
    for r in rs:
        if isinstance(r, dict):
            out.append(r)
        else:
            names = r.keys() if hasattr(r, "keys") else None
            out.append({k: r[k] for k in names} if names else dict(r))
    return out


@router.get("", response_class=HTMLResponse)
def overview(request: Request, admin=Depends(require_admin)):
    stats = mydata.pool_stats()
    pub = len(mydata.list_space_users())
    with db.use_cloud():
        conn = db.get_conn()
        accounts = conn.execute("SELECT COUNT(*) AS c FROM accounts").fetchone()
        audits = conn.execute("SELECT COUNT(*) AS c FROM audit_log").fetchone()
        recent = _rows(conn.execute(
            "SELECT actor, action, target, ts FROM audit_log ORDER BY id DESC LIMIT 8"))
        conn.close()
    g = lambda r: (r["c"] if isinstance(r, dict) else r[0])
    return render(request, "admin/overview.html", {
        "stats": stats, "pub": pub, "accounts": g(accounts),
        "audits": g(audits), "recent": recent})


# ---------------- 账号管理 ----------------

@router.get("/accounts", response_class=HTMLResponse)
def accounts_page(request: Request, admin=Depends(require_admin), q: str = ""):
    with db.use_cloud():
        conn = db.get_conn()
        if q:
            rows = _rows(conn.execute(
                "SELECT username, is_admin, status, created_at FROM accounts "
                "WHERE username LIKE ? ORDER BY account_id", ("%" + q + "%",)))
        else:
            rows = _rows(conn.execute(
                "SELECT username, is_admin, status, created_at FROM accounts ORDER BY account_id"))
        conn.close()
    return render(request, "admin/accounts.html", {"rows": rows, "q": q,
                                                   "msg": request.query_params.get("msg", "")})


@router.post("/accounts/toggle_status")
def toggle_status(request: Request, admin=Depends(require_admin)):
    if not security.same_origin(request):
        raise HTTPException(400, "非法请求来源")
    form = _form(request)
    username = str(form.get("username", ""))
    back = str(form.get("back", ""))
    actor = admin
    if username == actor:
        return RedirectResponse("/admin/accounts?msg=不能禁用自己", status_code=303)
    with db.use_cloud():
        conn = db.get_conn()
        row = conn.execute("SELECT status FROM accounts WHERE username=?", (username,)).fetchone()
        if row:
            st = row["status"] if isinstance(row, dict) else row[0]
            new = "active" if st == "disabled" else "disabled"
            conn.execute("UPDATE accounts SET status=? WHERE username=?", (new, username))
            conn.commit()
            security.audit(actor, "account_%s" % new, username)
        conn.close()
    return RedirectResponse(back or "/admin/accounts", status_code=303)


@router.post("/accounts/toggle_admin")
def toggle_admin(request: Request, admin=Depends(require_admin)):
    if not security.same_origin(request):
        raise HTTPException(400, "非法请求来源")
    form = _form(request)
    username = str(form.get("username", ""))
    actor = admin
    if username == actor:
        return RedirectResponse("/admin/accounts?msg=不能撤销自己的管理员", status_code=303)
    with db.use_cloud():
        conn = db.get_conn()
        row = conn.execute("SELECT is_admin FROM accounts WHERE username=?", (username,)).fetchone()
        if row:
            cur = row["is_admin"] if isinstance(row, dict) else row[0]
            conn.execute("UPDATE accounts SET is_admin=? WHERE username=?", (0 if cur else 1, username))
            conn.commit()
            security.audit(actor, "admin_%s" % ("revoke" if cur else "grant"), username)
        conn.close()
    return RedirectResponse("/admin/accounts", status_code=303)


@router.post("/accounts/reset_password")
def reset_password(request: Request, admin=Depends(require_admin)):
    if not security.same_origin(request):
        raise HTTPException(400, "非法请求来源")
    form = _form(request)
    username = str(form.get("username", ""))
    actor = admin
    temp = "Zt" + secrets.token_urlsafe(6)
    salt = secrets.token_hex(16)
    with db.use_cloud():
        conn = db.get_conn()
        conn.execute("UPDATE accounts SET pw_hash=?, salt=? WHERE username=?",
                     (hash_password(temp, salt), salt, username))
        conn.execute("DELETE FROM web_sessions WHERE owner=?", (username,))
        conn.commit()
        conn.close()
    security.audit(actor, "reset_password", username)
    return RedirectResponse("/admin/accounts?msg=%s 的临时密码：%s（仅显示一次，请转达后督促修改）"
                            % (username, temp), status_code=303)


# ---------------- 内容治理 ----------------

@router.get("/content", response_class=HTMLResponse)
def content_page(request: Request, admin=Depends(require_admin)):
    profiles = mydata.list_space_users()
    jobs = mydata.list_jobs(500)
    return render(request, "admin/content.html", {"profiles": profiles, "jobs": jobs})


@router.post("/content/retract_profile")
def retract_any(request: Request, admin=Depends(require_admin)):
    if not security.same_origin(request):
        raise HTTPException(400, "非法请求来源")
    form = _form(request)
    owner = str(form.get("owner", ""))
    mydata.retract_profile(owner)
    security.audit(admin, "retract_profile", owner)
    return RedirectResponse("/admin/content", status_code=303)


@router.post("/content/deactivate_job")
def deactivate_job(request: Request, admin=Depends(require_admin)):
    if not security.same_origin(request):
        raise HTTPException(400, "非法请求来源")
    form = _form(request)
    job_id = int(form.get("job_id", 0))
    with db.use_cloud():
        conn = db.get_conn()
        conn.execute("UPDATE jobs SET active=0 WHERE job_id=?", (job_id,))
        conn.commit()
        conn.close()
    security.audit(admin, "deactivate_job", str(job_id))
    return RedirectResponse("/admin/content", status_code=303)


# ---------------- 审计 ----------------

@router.get("/audit", response_class=HTMLResponse)
def audit_page(request: Request, admin=Depends(require_admin)):
    with db.use_cloud():
        conn = db.get_conn()
        rows = _rows(conn.execute(
            "SELECT actor, action, target, detail, ts FROM audit_log ORDER BY id DESC LIMIT 200"))
        conn.close()
    return render(request, "admin/audit.html", {"rows": rows})


# ---------------- 系统 ----------------

@router.get("/system", response_class=HTMLResponse)
def system_page(request: Request, admin=Depends(require_admin)):
    import platform
    import shutil
    import sys as _sys
    with db.use_cloud():
        conn = db.get_conn()
        ver = conn.execute("SELECT VERSION() AS v").fetchone()
        n_sessions = conn.execute("SELECT COUNT(*) AS c FROM web_sessions WHERE expires_at > NOW()").fetchone()
        conn.close()
    g = lambda r: (r["v"] if isinstance(r, dict) else r[0])
    gc = lambda r: (r["c"] if isinstance(r, dict) else r[0])
    return render(request, "admin/system.html", {
        "py": _sys.version.split()[0], "platform": platform.platform(),
        "mysql": g(ver), "disk": shutil.disk_usage("/"),
        "sessions": gc(n_sessions), "repo": "HnoNoe/job-delivery-system",
    })
