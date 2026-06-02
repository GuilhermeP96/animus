"""Admin panel authentication."""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from datetime import datetime, timezone
from typing import Optional

import jwt
from fastapi import HTTPException, Request, Response
from pydantic import BaseModel

# ── Config ──

# Fail-closed defaults: if the operator hasn't set credentials and a
# server secret, the admin panel refuses to authenticate. The legacy
# behaviour of falling back to "admin/admin" + a hard-coded secret
# silently exposed the panel on misconfigured hubs.

ADMIN_USER = os.environ.get("ANIMUS_ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ANIMUS_ADMIN_PASSWORD", "")
_ADMIN_SECRET_RAW = os.environ.get(
    "ANIMUS_ADMIN_SECRET",
    os.environ.get("ANIMUS_SERVER_SECRET", ""),
)
ADMIN_SECRET = _ADMIN_SECRET_RAW or "animus-fail-closed-no-secret"
_ADMIN_INSECURE = os.environ.get("ANIMUS_ADMIN_INSECURE", "0") == "1"
SESSION_COOKIE = "animus_session"
SESSION_EXPIRY = 8 * 3600  # 8 hours


def _admin_configured() -> bool:
    """Returns True iff the admin panel has real credentials and a
    real session secret. Allows ``ANIMUS_ADMIN_INSECURE=1`` to
    explicitly bypass for local-dev testing."""
    return bool(ADMIN_PASSWORD and _ADMIN_SECRET_RAW) or _ADMIN_INSECURE


class AdminSession(BaseModel):
    user: str
    exp: float
    iat: float


def validate_credentials(username: str, password: str) -> bool:
    """Constant-time credential validation. Fails closed when the
    admin panel has not been configured."""
    if not _admin_configured():
        return False
    user_ok = hmac.compare_digest(username.encode(), ADMIN_USER.encode())
    pass_ok = hmac.compare_digest(password.encode(), ADMIN_PASSWORD.encode())
    return user_ok and pass_ok


def create_session_token(username: str) -> str:
    """Create a JWT session token."""
    now = time.time()
    payload = {
        "sub": username,
        "iat": now,
        "exp": now + SESSION_EXPIRY,
        "iss": "animus-hub",
    }
    return jwt.encode(payload, ADMIN_SECRET, algorithm="HS256")


def verify_session_token(token: str) -> Optional[AdminSession]:
    """Verify and decode a session token."""
    try:
        payload = jwt.decode(token, ADMIN_SECRET, algorithms=["HS256"], options={"require": ["sub", "exp", "iat"]})
        return AdminSession(
            user=payload["sub"],
            exp=payload["exp"],
            iat=payload["iat"],
        )
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None


def set_session_cookie(response: Response, token: str) -> None:
    """Set the session cookie on a response."""
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        secure=os.environ.get("ANIMUS_SECURE_COOKIES", "true").lower() == "true",
        samesite="lax",
        max_age=SESSION_EXPIRY,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    """Clear the session cookie."""
    response.delete_cookie(key=SESSION_COOKIE, path="/")


def get_current_admin(request: Request) -> Optional[AdminSession]:
    """Extract admin session from request cookies."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    return verify_session_token(token)


def require_admin(request: Request) -> AdminSession:
    """Dependency that requires a valid admin session."""
    session = get_current_admin(request)
    if not session:
        raise HTTPException(status_code=401, detail="Authentication required")
    return session
