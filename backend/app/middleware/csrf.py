"""Double-submit CSRF protection for cookie-less JWT API (header token)."""
from __future__ import annotations

import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import settings

_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_CSRF_EXEMPT_PREFIXES = (
    "/api/v1/auth/login",
    "/api/v1/auth/register",
    "/api/v1/auth/refresh",
    "/api/v1/auth/change-password",
    "/api/v1/auth/recover",
    "/api/v1/auth/reset",
    "/api/v1/auth/wasnt-me",
    "/api/v1/auth/verify-email/",
    "/api/v1/webhooks/email/",
    "/api/v1/applications/",
    "/api/v1/admissions/apply",
    "/api/v1/billing/webhook/",
    "/api/v1/health",
    "/api/chat",  # hourly health regression alias (Bearer auth, no browser cookie)
    "/metrics",
)


def _csrf_token_response() -> JSONResponse:
    token = secrets.token_urlsafe(32)
    response = JSONResponse({"csrf_token": token})
    response.set_cookie(
        settings.CSRF_COOKIE_NAME,
        token,
        httponly=False,
        samesite="lax",
        path="/",
        secure=settings.is_production,
        max_age=3600,
    )
    return response


class CsrfMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        # The browser client waits on this GET before any authenticated POST.
        # A 404 here aborts the save even when protection is off.
        if request.method == "GET" and path.rstrip("/") == f"{settings.API_PREFIX}/auth/csrf-token":
            return _csrf_token_response()

        if not settings.CSRF_PROTECTION_ENABLED:
            return await call_next(request)

        if request.method in _UNSAFE_METHODS:
            if any(path.startswith(p) for p in _CSRF_EXEMPT_PREFIXES):
                return await call_next(request)
            if request.headers.get("Authorization", "").startswith("Bearer "):
                header = request.headers.get(settings.CSRF_HEADER_NAME, "")
                cookie = request.cookies.get(settings.CSRF_COOKIE_NAME, "")
                if not header or not cookie or not secrets.compare_digest(header, cookie):
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "CSRF token missing or invalid"},
                    )

        return await call_next(request)
