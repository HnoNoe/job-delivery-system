"""FastAPI 依赖注入：当前用户 / 管理员门禁。"""
from fastapi import Depends, HTTPException, Request, status

from server import security


def current_user(request: Request):
    """返回 (owner, is_admin)；未登录 401 跳登录。"""
    token = request.cookies.get(security.SESSION_COOKIE, "")
    owner, is_admin = security.owner_of_token(token)
    if owner is None:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER,
                            headers={"Location": "/login"})
    return owner, is_admin


def require_admin(user=Depends(current_user)):
    owner, is_admin = user
    if not is_admin:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER,
                            headers={"Location": "/app"})
    return owner
