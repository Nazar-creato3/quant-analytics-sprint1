"""User TOTP 2FA setup / status / disable / reauth endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.client_ip import get_client_ip
from app.core.deps import get_current_user_email, get_db
from app.core.logging import get_logger
from app.core.security import verify_password
from app.db.models import AuditLog, User, UserRole
from app.domain.rbac import has_permission, map_legacy_user_role
from app.schemas.two_factor import (
    TwoFactorDisableIn,
    TwoFactorEnableConfirmIn,
    TwoFactorEnableConfirmOut,
    TwoFactorEnableInitiateOut,
    TwoFactorReauthIn,
    TwoFactorStatusOut,
)
from app.services.two_factor import (
    VERIFY_LOCK_WINDOW_SEC,
    VERIFY_MAX_FAILURES,
    clear_setup_secret,
    decrypt_totp_secret,
    encrypt_totp_secret,
    generate_backup_codes,
    generate_totp_secret,
    hash_backup_codes,
    load_setup_secret,
    otpauth_manual_hint,
    provisioning_uri,
    qr_code_data_url,
    store_setup_secret,
    utcnow,
    verify_fail_key,
    verify_totp,
)
from app.utils.cache import rate_limit_clear, rate_limit_peek, rate_limit_record_failure

router = APIRouter(prefix="/two-factor", tags=["two-factor"])
logger = get_logger(__name__)


async def _current_user(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> User:
    result = await db.execute(select(User).where(User.email == email.lower()))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    return user


def _is_admin_user(user: User) -> bool:
    role = map_legacy_user_role(user.role.value if hasattr(user.role, "value") else str(user.role))
    return has_permission(role, "*") or (
        (user.role.value if hasattr(user.role, "value") else str(user.role)) == UserRole.ADMIN.value
    )


async def _audit(
    db: AsyncSession,
    *,
    user: User,
    action: str,
    request: Request | None,
    success: bool = True,
    details: dict | None = None,
    error: str | None = None,
) -> None:
    ip = get_client_ip(request) if request else None
    ua = request.headers.get("user-agent") if request else None
    db.add(
        AuditLog(
            user_id=user.id,
            action=action,
            resource_type="two_factor",
            resource_id=user.id,
            details=details or {},
            ip_address=ip,
            user_agent=(ua or "")[:256] or None,
            success=success,
            error=error,
        )
    )
    await db.commit()


async def _enforce_verify_rate(user_id: str) -> None:
    allowed, _, retry_after = await rate_limit_peek(
        verify_fail_key(user_id),
        VERIFY_MAX_FAILURES,
        fail_closed=True,
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Слишком много попыток 2FA. Повторите через {retry_after or VERIFY_LOCK_WINDOW_SEC} сек.",
        )


@router.get("/status", response_model=TwoFactorStatusOut)
async def two_factor_status(
    user: User = Depends(_current_user),
) -> TwoFactorStatusOut:
    remaining = None
    if user.two_factor_enabled and isinstance(user.two_factor_backup_codes, list):
        remaining = len(user.two_factor_backup_codes)
    return TwoFactorStatusOut(
        enabled=bool(user.two_factor_enabled),
        enabled_at=user.two_factor_enabled_at.isoformat() if user.two_factor_enabled_at else None,
        backup_codes_remaining=remaining,
        required_for_admin=_is_admin_user(user),
    )


@router.post("/enable/initiate", response_model=TwoFactorEnableInitiateOut)
async def enable_initiate(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_current_user),
) -> TwoFactorEnableInitiateOut:
    if user.two_factor_enabled:
        raise HTTPException(status_code=400, detail="2FA уже включена")
    secret = generate_totp_secret()
    await store_setup_secret(user.id, secret)
    uri = provisioning_uri(user.email, secret)
    await _audit(db, user=user, action="two_factor_setup_initiated", request=request)
    return TwoFactorEnableInitiateOut(
        secret=secret,
        provisioning_uri=uri,
        qr_code_base64=qr_code_data_url(uri),
        manual_hint=otpauth_manual_hint(secret, user.email),
    )


@router.post("/enable/confirm", response_model=TwoFactorEnableConfirmOut)
async def enable_confirm(
    body: TwoFactorEnableConfirmIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_current_user),
) -> TwoFactorEnableConfirmOut:
    if user.two_factor_enabled:
        raise HTTPException(status_code=400, detail="2FA уже включена")
    await _enforce_verify_rate(user.id)
    secret = await load_setup_secret(user.id)
    if not secret:
        raise HTTPException(
            status_code=400,
            detail="Сессия настройки 2FA истекла. Начните заново.",
        )
    if not verify_totp(secret, body.code):
        await rate_limit_record_failure(
            verify_fail_key(user.id),
            VERIFY_MAX_FAILURES,
            VERIFY_LOCK_WINDOW_SEC,
            fail_closed=True,
        )
        await _audit(
            db,
            user=user,
            action="two_factor_enable_failed",
            request=request,
            success=False,
            error="invalid_totp",
        )
        raise HTTPException(status_code=400, detail="Неверный код из приложения")

    plain_codes = generate_backup_codes(10)
    user.two_factor_secret = encrypt_totp_secret(secret)
    user.two_factor_enabled = True
    user.two_factor_backup_codes = hash_backup_codes(plain_codes)
    user.two_factor_enabled_at = utcnow()
    user.two_factor_disabled_at = None
    await db.commit()
    await clear_setup_secret(user.id)
    await rate_limit_clear(verify_fail_key(user.id))
    await _audit(db, user=user, action="two_factor_enabled", request=request)
    return TwoFactorEnableConfirmOut(
        success=True,
        backup_codes=plain_codes,
        message=(
            "2FA включена. Сохраните резервные коды — они показываются один раз. "
            "Старые коды при перегенерации перестанут работать."
        ),
    )


@router.post("/disable")
async def disable_2fa(
    body: TwoFactorDisableIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_current_user),
) -> dict:
    if not user.two_factor_enabled or not user.two_factor_secret:
        raise HTTPException(status_code=400, detail="2FA не включена")
    if _is_admin_user(user):
        raise HTTPException(
            status_code=403,
            detail="Администраторы не могут отключить 2FA. Обратитесь к владельцу платформы.",
        )
    if not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Неверный пароль")
    await _enforce_verify_rate(user.id)
    secret = decrypt_totp_secret(user.two_factor_secret)
    if not verify_totp(secret, body.code):
        await rate_limit_record_failure(
            verify_fail_key(user.id),
            VERIFY_MAX_FAILURES,
            VERIFY_LOCK_WINDOW_SEC,
            fail_closed=True,
        )
        raise HTTPException(status_code=400, detail="Неверный код 2FA")

    user.two_factor_secret = None
    user.two_factor_enabled = False
    user.two_factor_backup_codes = None
    user.two_factor_disabled_at = utcnow()
    await db.commit()
    await rate_limit_clear(verify_fail_key(user.id))
    await _audit(db, user=user, action="two_factor_disabled", request=request)
    return {"success": True, "message": "2FA отключена"}


@router.post("/regenerate-backup-codes", response_model=TwoFactorEnableConfirmOut)
async def regenerate_backup_codes(
    body: TwoFactorEnableConfirmIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_current_user),
) -> TwoFactorEnableConfirmOut:
    if not user.two_factor_enabled or not user.two_factor_secret:
        raise HTTPException(status_code=400, detail="2FA не включена")
    await _enforce_verify_rate(user.id)
    secret = decrypt_totp_secret(user.two_factor_secret)
    if not verify_totp(secret, body.code):
        await rate_limit_record_failure(
            verify_fail_key(user.id),
            VERIFY_MAX_FAILURES,
            VERIFY_LOCK_WINDOW_SEC,
            fail_closed=True,
        )
        raise HTTPException(status_code=400, detail="Неверный код 2FA")
    plain_codes = generate_backup_codes(10)
    user.two_factor_backup_codes = hash_backup_codes(plain_codes)
    await db.commit()
    await rate_limit_clear(verify_fail_key(user.id))
    await _audit(db, user=user, action="two_factor_backup_regenerated", request=request)
    return TwoFactorEnableConfirmOut(
        success=True,
        backup_codes=plain_codes,
        message="Новые резервные коды созданы. Старые больше не действительны.",
    )


@router.post("/reauth")
async def reauth_sensitive(
    body: TwoFactorReauthIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_current_user),
) -> dict:
    """Confirm TOTP for critical actions; returns short-lived reauth_token claim marker via Redis."""
    if not user.two_factor_enabled or not user.two_factor_secret:
        raise HTTPException(status_code=400, detail="2FA не включена")
    await _enforce_verify_rate(user.id)
    secret = decrypt_totp_secret(user.two_factor_secret)
    if not verify_totp(secret, body.code):
        await rate_limit_record_failure(
            verify_fail_key(user.id),
            VERIFY_MAX_FAILURES,
            VERIFY_LOCK_WINDOW_SEC,
            fail_closed=True,
        )
        await _audit(
            db,
            user=user,
            action="two_factor_reauth_failed",
            request=request,
            success=False,
            error="invalid_totp",
        )
        raise HTTPException(status_code=401, detail="Неверный код 2FA")
    from app.utils.cache import cache_set
    from app.utils.helpers import new_uuid
    from app.services.two_factor import reauth_cache_key

    token = new_uuid()
    await cache_set(reauth_cache_key(user.id, token), {"ok": True}, ttl=300)
    await rate_limit_clear(verify_fail_key(user.id))
    await _audit(db, user=user, action="two_factor_reauth_ok", request=request)
    return {"success": True, "reauth_token": token, "expires_in": 300}
