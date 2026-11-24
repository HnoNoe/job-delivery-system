"""Jinja2 渲染封装：主题色板注入 + 全局导航上下文。"""
import os

from fastapi import Request
from fastapi.templating import Jinja2Templates

_TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")


def get_templates():
    t = Jinja2Templates(directory=_TEMPLATES_DIR)
    t.env.policies["json.dumps_kwargs"] = {"ensure_ascii": False}
    return t


def render(request: Request, name: str, context: dict, status_code: int = 200):
    templates = get_templates()
    ctx = {"request": request, "user": None, "is_admin": False}
    ctx.update(context)
    # 已登录用户从 cookie 注入导航上下文（模板需要 username）
    from server import security
    token = request.cookies.get(security.SESSION_COOKIE, "")
    owner, is_admin = security.owner_of_token(token)
    if owner:
        ctx["user"] = owner
        ctx["is_admin"] = is_admin
    return templates.TemplateResponse(name, ctx, status_code=status_code)
