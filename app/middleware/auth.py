from __future__ import annotations

import bcrypt
from fastapi import HTTPException, Depends, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from starlette.status import HTTP_401_UNAUTHORIZED

from app.config import get_settings

security = HTTPBasic()


def _hash_password(password: str) -> str:
    """Hash a password with bcrypt."""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def _verify_password(plain: str, hashed: str) -> bool:
    """Verify a password against its hash."""
    return bcrypt.checkpw(plain.encode('utf-8'), hashed.encode('utf-8'))


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
    # Support both plain text and bcrypt hashed passwords
    stored = settings.admin_password
    if stored.startswith('$2b$') or stored.startswith('$2a$'):
        # bcrypt hash
        if not _verify_password(credentials.password, stored):
            raise HTTPException(
                status_code=HTTP_401_UNAUTHORIZED,
                detail="密码错误",
            )
    else:
        # Plain text fallback (for backwards compatibility)
        if credentials.password != stored:
            raise HTTPException(
                status_code=HTTP_401_UNAUTHORIZED,
                detail="密码错误",
            )
    response = JSONResponse(content={"detail": "登录成功"})
    response.set_cookie(key="session", value="authenticated", httponly=True)
    return response


def hash_admin_password(password: str) -> str:
    """Hash admin password with bcrypt. Call this once after setting ADMIN_PASSWORD."""
    return _hash_password(password)
