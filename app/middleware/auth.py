from __future__ import annotations

from fastapi import HTTPException, Depends, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from starlette.status import HTTP_401_UNAUTHORIZED

from app.config import get_settings

security = HTTPBasic()


def require_auth(request: Request) -> None:
    settings = get_settings()
    if not settings.require_auth:
        return
    session = request.cookies.get("session")
    if not session:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="未登录",
        )


def login_endpoint(
    credentials: HTTPBasicCredentials = Depends(security),
) -> JSONResponse:
    settings = get_settings()
    if not settings.require_auth:
        return JSONResponse(content={"detail": "未启用认证"})
    if credentials.password != settings.admin_password:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="密码错误",
        )
    response = JSONResponse(content={"detail": "登录成功"})
    response.set_cookie(key="session", value="authenticated", httponly=True)
    return response
