"""
FastAPI dependency injection providers.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import JWTError, access_jti_revoked, decode_token
from app.db.rls import set_session_user_id
from app.db.session import AsyncSessionLocal
from app.domain.admin_security import admin_path_allowed_for_role, requires_reauth
from app.domain.rbac import IdentityORM, SystemRole, has_permission

logger = get_logger(__name__)
bearer_scheme = HTTPBearer(auto_error=True)
admin_bearer_scheme = HTTPBearer(auto_error=True, scheme_name="AdminBearer")


_RLS_UID_CACHE: dict[str, str] = {}


async def _rls_user_id_from_request(session: AsyncSession, request: Request | None) -> str | None:
    """User id for row-level security from a valid user access token, else None.

    Many authenticated endpoints take this plain session. The database role has no RLS bypass,
    so without app.user_id every user-owned table (reports, manoeuvres, bots, trades…) reads
    as empty. Binding the caller here keeps those endpoints scoped to their own rows.
    """
    if request is None:
        return None
    auth = request.headers.get("authorization") or ""
    if not auth.lower().startswith("bearer "):
        return None
    try:
        payload = decode_token(auth.split(" ", 1)[1].strip())
    except Exception:  # noqa: BLE001 — invalid token: auth dependency will reject it
        return None
    email = payload.get("sub")
    if payload.get("type") != "access" or payload.get("aud") == settings.ADMIN_TOKEN_AUDIENCE:
        return None
    if not isinstance(email, str) or not email:
        return None
    key = email.lower()
    if key in _RLS_UID_CACHE:
        return _RLS_UID_CACHE[key]
    from app.db.models import User

    uid = (await session.execute(select(User.id).where(User.email == key))).scalar_one_or_none()
    if uid:
        if len(_RLS_UID_CACHE) > 5000:
            _RLS_UID_CACHE.clear()
        _RLS_UID_CACHE[key] = str(uid)
    return str(uid) if uid else None


async def get_db(request: Request = None) -> AsyncGenerator[AsyncSession, None]:  # type: ignore[assignment]
    """Yield an async database session for the current request (RLS-bound to the caller if signed in)."""
    session = AsyncSessionLocal()
    try:
        try:
            uid = await _rls_user_id_from_request(session, request)
            if uid:
                await set_session_user_id(session, uid)
        except Exception as exc:  # noqa: BLE001 — never block a request on the RLS bind
            logger.debug("RLS bind skipped", error=str(exc))
            await session.rollback()
        yield session
    except Exception as exc:
        logger.exception("Database dependency failed: %s", exc)
        raise
    finally:
        await session.close()


# Reachable without a confirmed phone: auth flows, legal texts, the user's own data rights.
PHONE_EXEMPT_PREFIXES = (
    "/api/v1/auth/",
    "/api/v1/legal",
    "/api/v1/subject-rights",
    "/api/v1/privacy",
    "/api/v1/health",
)


def phone_gate(payload: dict[str, Any], path: str) -> None:
    """403 until the account has a confirmed Russian mobile number (149-FZ art. 10.6)."""
    if not settings.PHONE_SIGNIN_REQUIRED or settings.QA_E2E_DEMO:
        return
    if payload.get("pv") is True:
        return
    if any(path.startswith(p) for p in PHONE_EXEMPT_PREFIXES):
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="phone_confirmation_required")


async def get_current_user_payload(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> dict[str, Any]:
    """Validate Bearer token and return decoded JWT payload."""
    payload = _decode_access(credentials)
    phone_gate(payload, request.url.path)
    return payload


def _decode_access(credentials: HTTPAuthorizationCredentials) -> dict[str, Any]:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(credentials.credentials)
        subject = payload.get("sub", "")
        token_type = payload.get("type", "")
        audience = payload.get("aud")
        if audience == settings.ADMIN_TOKEN_AUDIENCE:
            raise credentials_exception
        if not isinstance(subject, str) or not subject or token_type != "access":
            raise credentials_exception
        if access_jti_revoked(payload.get("jti")):
            raise credentials_exception
        return payload
    except JWTError as exc:
        logger.warning("JWT validation failed: %s", exc)
        raise credentials_exception from exc
    except Exception as exc:
        logger.exception("Unexpected auth dependency failure: %s", exc)
        raise credentials_exception from exc


async def get_admin_session_payload(
    credentials: HTTPAuthorizationCredentials = Depends(admin_bearer_scheme),
) -> dict[str, Any]:
    """Validate admin-audience Bearer token."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Admin session required",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(credentials.credentials)
        if payload.get("type") != "access":
            raise credentials_exception
        if payload.get("aud") != settings.ADMIN_TOKEN_AUDIENCE:
            raise credentials_exception
        if not payload.get("is_admin"):
            raise credentials_exception
        return payload
    except JWTError as exc:
        raise credentials_exception from exc


async def get_current_user_email(
    payload: dict[str, Any] = Depends(get_current_user_payload),
) -> str:
    """Extract email from validated JWT payload."""
    subject = payload.get("sub")
    if not isinstance(subject, str) or not subject:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return subject


async def get_db_after_auth(
    request: Request,
    _payload: dict[str, Any] = Depends(get_current_user_payload),
) -> AsyncGenerator[AsyncSession, None]:
    """Open a DB session only after JWT validation succeeds (fail-fast auth)."""
    async for session in get_db(request):
        yield session


async def get_user_db(
    email: str = Depends(get_current_user_email),
) -> AsyncGenerator[AsyncSession, None]:
    """Authenticated DB session with Postgres RLS user context set."""
    from app.services.portfolio.user_scope import get_user_by_email

    session = AsyncSessionLocal()
    try:
        user = await get_user_by_email(session, email)
        if user is not None and not bool(getattr(user, "is_active", True)):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        await set_session_user_id(session, user.id if user else None)
        yield session
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Authenticated database dependency failed: %s", exc)
        raise
    finally:
        await session.close()


async def get_admin_user_email(
    payload: dict[str, Any] = Depends(get_admin_session_payload),
) -> str:
    subject = payload.get("sub")
    if not isinstance(subject, str) or not subject:
        raise HTTPException(status_code=401, detail="Invalid admin token")
    return subject


async def require_admin_mfa(
    email: str = Depends(get_admin_user_email),
    db: AsyncSession = Depends(get_db),
) -> IdentityORM:
    """403 when admin identity has MFA disabled — hard gate on all /admin/* routes."""
    result = await db.execute(select(IdentityORM).where(IdentityORM.primary_email == email))
    identity = result.scalar_one_or_none()
    if identity is None or not identity.mfa_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="MFA must be enabled and verified before accessing admin routes",
        )
    role = SystemRole(identity.system_role)
    if not admin_path_allowed_for_role(role):
        raise HTTPException(status_code=403, detail="Admin path denied for this identity")
    return identity


def require_admin_permission(permission: str):
    """Factory: admin route dependency with optional sensitive-action reauth marker."""

    async def _dependency(identity: IdentityORM = Depends(require_admin_mfa)) -> IdentityORM:
        role = SystemRole(identity.system_role)
        if not has_permission(role, permission) and permission != "admin.session":
            raise HTTPException(status_code=403, detail=f"Permission denied: {permission}")
        if requires_reauth(permission):
            identity._sensitive_action_verified = True  # type: ignore[attr-defined]
        return identity

    return _dependency


async def require_admin(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Require current DB role with ``*`` — do not trust a stale JWT ``is_admin`` claim."""
    from app.core.rbac_deps import get_user_and_role

    _user, role = await get_user_and_role(db, email)
    if not has_permission(role, "*"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return {"sub": email, "is_admin": True}


def _self_test() -> None:
    assert callable(get_current_user_payload)
    assert callable(get_current_user_email)
    assert callable(require_admin)
    assert callable(get_db)


_self_test()
