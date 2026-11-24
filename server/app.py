"""FastAPI 应用装配。运行（仓库根目录）：
    uvicorn server.app:app --host 127.0.0.1 --port 8000
环境变量（systemd 里配置）：
    JOBDELIVERY_DB_URL=mysql://...   服务端全量走云端库（默认本地 SQLite，仅开发用）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from server.routers import admin, auth, client, space
from server.templating import render

app = FastAPI(title="智投链 · Web 客户端与管理端", docs_url=None, redoc_url=None)

_STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
app.mount("/static", StaticFiles(directory=_STATIC), name="static")

app.include_router(auth.router)
app.include_router(client.router)
app.include_router(space.router)
app.include_router(admin.router)


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    from server import security
    token = request.cookies.get(security.SESSION_COOKIE, "")
    owner, _ = security.owner_of_token(token)
    if owner:
        return RedirectResponse("/app")
    return RedirectResponse("/login")
