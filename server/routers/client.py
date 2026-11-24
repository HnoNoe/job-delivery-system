"""Web 客户端页面：仪表盘 / 简历 / 岗位池 / 统一空间广场 / 我的画像。"""
import io
import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

import mydata
import schema
from server import security
from server.deps import current_user
from server.templating import render

router = APIRouter(prefix="/app", tags=["client"])


@router.get("", response_class=HTMLResponse)
def dashboard(request: Request, user=Depends(current_user)):
    owner, is_admin = user
    stats = mydata.pool_stats()
    published = any(p["owner"] == owner for p in mydata.list_space_users())
    resume = mydata.load_resume(owner)
    snaps = mydata.list_my_profiles(owner)
    return render(request, "dashboard.html", {
        "owner": owner, "stats": stats, "published": published,
        "has_resume": resume is not None, "snap_count": len(snaps),
    })


# ---------------- 简历 ----------------

@router.get("/resume", response_class=HTMLResponse)
def resume_page(request: Request, user=Depends(current_user)):
    owner, _ = user
    r = mydata.load_resume(owner)
    data = {}
    if r:
        data = dict(r["l0"])
        if r["l3"].get("意向岗位"):
            data["意向岗位"] = r["l3"]["意向岗位"]
        data["经历"] = r["experiences"]
    return render(request, "resume.html", {"data": data, "fields": schema.L0_FIELDS,
                                           "saved": request.query_params.get("saved") == "1"})


@router.post("/resume")
def resume_save(request: Request, user=Depends(current_user)):
    if not security.same_origin(request):
        raise HTTPException(400, "非法请求来源")
    owner, _ = user
    form = awaitless_form(request)
    意向岗位 = form.get("意向岗位", "")
    经历 = form.get("经历", "")
    parsed = {k: str(v).strip() for k, v in form.items()
              if v and k not in ("意向岗位", "经历")}
    if str(意向岗位).strip():
        parsed["意向岗位"] = str(意向岗位).strip()
    try:
        exps = json.loads(str(经历) or "[]")
        if isinstance(exps, list):
            parsed["经历"] = exps
    except ValueError:
        pass
    mydata.save_resume(owner, parsed)
    return RedirectResponse("/app/resume?saved=1", status_code=303)


def awaitless_form(request: Request):
    """同步获取表单字段（非 async 路由内 request.form() 需要异步，改用 starlette 解析）。"""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
    if loop.is_running():
        raise RuntimeError("async 路由内不可用")
    return loop.run_until_complete(request.form())


@router.post("/resume/upload")
def resume_upload(request: Request, user=Depends(current_user),
                  file: UploadFile = File(...)):
    owner, _ = user
    if not file.filename.lower().endswith(".pdf"):
        return RedirectResponse("/app/resume?saved=0&err=only_pdf", status_code=303)
    import pdfplumber
    import resume_ai
    raw = file.file.read()
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    parsed = resume_ai.smart_parse(text) or {}
    if parsed:
        mydata.save_resume(owner, parsed)
    return RedirectResponse("/app/resume?saved=1&parsed=%d" % len(parsed), status_code=303)


# ---------------- 岗位池 ----------------

@router.get("/jobs", response_class=HTMLResponse)
def jobs_page(request: Request, user=Depends(current_user)):
    q = request.query_params.get("q", "").strip()
    jobs = mydata.list_jobs(1000)
    if q:
        jobs = [j for j in jobs if q in j.get("岗位名称", "") or q in j.get("单位名称", "")]
    return render(request, "jobs.html", {"jobs": jobs[:500], "q": q, "total": len(jobs)})


# ---------------- 统一空间广场 ----------------

@router.get("/plaza", response_class=HTMLResponse)
def plaza_page(request: Request, user=Depends(current_user)):
    owner, _ = user
    try:
        n_users = len(mydata.list_space_users())
        n_jobs = len(mydata.list_space_jobs(5000))
    except Exception:
        n_users, n_jobs = 0, 0
    return render(request, "plaza.html", {"n_users": n_users, "n_jobs": n_jobs,
                                          "highlight": owner})


# ---------------- 我的画像 ----------------

@router.get("/profiles", response_class=HTMLResponse)
def profiles_page(request: Request, user=Depends(current_user)):
    owner, _ = user
    rows = []
    for r in mydata.list_my_profiles(owner):
        g = lambda k, i: (r[k] if isinstance(r, dict) else r[i])
        rows.append({"snap_id": g("snap_id", 0), "visibility": g("visibility", 1),
                     "ts": str(g("ts", 2)), "delivered": g("delivered_count", 3),
                     "interview": g("interview_count", 4)})
    published = any(p["owner"] == owner for p in mydata.list_space_users())
    return render(request, "profiles.html", {"rows": rows, "published": published,
                                             "msg": request.query_params.get("msg", "")})


@router.post("/profiles/publish")
def profiles_publish(request: Request, user=Depends(current_user)):
    if not security.same_origin(request):
        raise HTTPException(400, "非法请求来源")
    owner, _ = user
    ok, msg = mydata.push_profile(owner)
    return RedirectResponse("/app/profiles?msg=%s" % msg, status_code=303)


@router.post("/profiles/retract")
def profiles_retract(request: Request, user=Depends(current_user)):
    if not security.same_origin(request):
        raise HTTPException(400, "非法请求来源")
    owner, _ = user
    ok, msg = mydata.retract_profile(owner)
    return RedirectResponse("/app/profiles?msg=%s" % msg, status_code=303)
