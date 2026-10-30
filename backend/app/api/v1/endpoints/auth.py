"""
Authentication endpoints: login, register, refresh token, whitelist management.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.client_ip import get_client_ip
from app.core.config import settings
from app.core.deps import (
    get_current_user_email,
    get_current_user_payload,
    get_db,
    get_db_after_auth,
    require_admin,
)
from app.core.logging import get_logger
from app.core.security import (
    JWTError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    password_needs_upgrade,
    register_refresh_family,
    revoke_access_jti,
    rotate_refresh_token,
    revoke_all_refresh_families,
    verify_password,
)
from app.db.models import AuditLog, User, UserRole
from app.domain.admissions import AdmissionCaseCreate, AdmissionStatus
from app.domain.device_identity import ip_range_key
from app.core.rbac_deps import get_identity_for_email
from app.domain.rbac import TrustLevel, has_permission, map_legacy_user_role
from app.schemas.schemas import (
    LoginRequest,
    PasswordChangeConfirmIn,
    PasswordChangeRequestIn,
    RecoverPasswordIn,
    RecoverPasswordOut,
    RefreshRequest,
    ResetPasswordIn,
    GenericMessageOut,
    TokenResponse,
    UserCreate,
    UserOut,
    VerifyEmailConfirmIn,
    VerifyEmailRequestIn,
)
from app.domain.application_flow import ChangePasswordIn
from app.schemas.two_factor import TwoFactorLoginVerifyIn
from app.services.subscription.paywall import paywall_subscription_service
from app.services.webauthn.service import webauthn_service
from app.services.access_policy.service import access_policy_service
from app.services.admissions.service import admissions_service
from app.services.device_identity.service import device_identity_service
from app.services.signup_abuse.guard import score_signup_abuse_async
from app.services.two_factor import (
    VERIFY_LOCK_WINDOW_SEC,
    VERIFY_MAX_FAILURES,
    clear_pending_login,
    consume_backup_code,
    decrypt_totp_secret,
    load_pending_login,
    store_pending_login,
    verify_fail_key,
    verify_totp,
)
from app.utils.helpers import new_uuid
from app.utils.cache import rate_limit_clear, rate_limit_peek, rate_limit_record_failure
from app.services.auth.password_change import (
    apply_new_password_hash,
    confirm_password_change,
    request_password_change,
)
from app.services.auth.recovery import (
    report_unauthorized_password_change,
    request_password_recovery,
    reset_password_with_token,
)
from app.services.auth.user_verification import (
    confirm_email_verification,
    resend_verification_email,
    send_verification_email_for_user,
    user_needs_verification,
)
from app.utils.cache import (
    rate_limit_check,
    rate_limit_clear,
    rate_limit_peek,
    rate_limit_record_failure,
)

def phone_claim(user: User | None) -> bool:
    """Access tokens carry whether the account has a confirmed Russian mobile number."""
    return bool(user is not None and getattr(user, "phone_verified_at", None))


router = APIRouter(prefix="/auth", tags=["auth"])
logger = get_logger(__name__)

_AUTH_CLIENT_ERRORS = {
    "max_accounts_per_device": (
        "На этом устройстве уже зарегистрирован аккаунт. "
        "Войдите в существующий или используйте другое устройство."
    ),
}
_GENERIC_LOGIN_FAIL = "Неверный email или пароль"
_GENERIC_DEVICE_FAIL = "Вход с этого устройства недоступен"
_GENERIC_WEBAUTHN_FAIL = "Не удалось подтвердить устройство"


def _client_error_detail(exc: BaseException, *, fallback: str) -> str:
    """User-facing auth/device errors — never raw exception codes (GA16-295)."""
    return _AUTH_CLIENT_ERRORS.get(str(exc).strip(), fallback)


async def _write_audit(
    db: AsyncSession,
    *,
    action: str,
    user_id: str | None = None,
    resource_id: str | None = None,
    details: dict | None = None,
    ip: str | None = None,
    success: bool = True,
    error: str | None = None,
) -> None:
    log = AuditLog(
        user_id=user_id,
        action=action,
        resource_type="user",
        resource_id=resource_id,
        details=details or {},
        ip_address=ip,
        success=success,
        error=error,
    )
    db.add(log)
    await db.commit()


def _registration_allowed(_email: str) -> bool:
    """Closed until approved legal texts + RKN notice; demo contour may use drafts."""
    from app.services.legal.gates import registration_open

    return registration_open()


def _login_allowed(user: User) -> bool:
    if not user.is_active:
        return False
    if settings.OPEN_REGISTRATION:
        return True
    return bool(user.is_whitelisted)


def _session_denied_detail(user: User | None) -> str | None:
    """Same gates as login, used on refresh so tokens cannot outlive a lock."""
    if user is None or not user.is_active:
        return "Account is not available."
    if not _login_allowed(user):
        return "Нет доступа к платформе. Обратитесь к администратору."
    if user_needs_verification(user):
        return "Email verification required. Check your inbox or request a new verification link."
    return None


async def _require_bot_check(token: str | None, ip: str | None) -> None:
    from app.services.application.turnstile import verify_turnstile

    if not settings.TURNSTILE_SECRET_KEY:
        return
    if not await verify_turnstile(token or "", ip):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Проверка безопасности не пройдена. Обновите страницу.",
        )


def _login_rate_limit_key(email: str, ip: str | None) -> str:
    """Per email+IP — avoids one NAT/proxy IP blocking unrelated users."""
    return f"login_fail:{email.strip().lower()}:{ip or 'unknown'}"


def _login_rate_limit_email_key(email: str) -> str:
    return f"login_fail_email:{email.strip().lower()}"


def _login_rate_limit_error(retry_after_seconds: int) -> HTTPException:
    retry_after = max(1, retry_after_seconds)
    minutes = max(1, (retry_after + 59) // 60)
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=(
            f"Слишком много неудачных попыток входа. "
            f"Повторите через {minutes} мин."
        ),
        headers={"Retry-After": str(retry_after)},
    )


async def _enforce_login_rate_limit(email: str, ip: str | None) -> None:
    """Block when prior failed password attempts exceeded the window limit."""
    keys = (
        (_login_rate_limit_key(email, ip), settings.LOGIN_RATE_LIMIT_MAX_FAILURES),
        (
            _login_rate_limit_email_key(email),
            settings.LOGIN_RATE_LIMIT_MAX_FAILURES_PER_EMAIL,
        ),
    )
    for key, max_failures in keys:
        allowed, _, retry_after = await rate_limit_peek(
            key,
            max_failures,
            fail_closed=True,
        )
        if not allowed:
            raise _login_rate_limit_error(retry_after)


async def _record_failed_login(email: str, ip: str | None) -> None:
    keys = (
        (
            _login_rate_limit_key(email, ip),
            settings.LOGIN_RATE_LIMIT_MAX_FAILURES,
            settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS,
        ),
        (
            _login_rate_limit_email_key(email),
            settings.LOGIN_RATE_LIMIT_MAX_FAILURES_PER_EMAIL,
            settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS,
        ),
    )
    for key, max_failures, window_seconds in keys:
        allowed, _, retry_after = await rate_limit_record_failure(
            key,
            max_failures,
            window_seconds,
            fail_closed=True,
        )
        if not allowed:
            raise _login_rate_limit_error(retry_after)


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Authenticate user and return JWT tokens."""
    ip = get_client_ip(request)
    email = body.email.lower().strip()

    await _enforce_login_rate_limit(email, ip)

    result = await db.execute(select(User).where(User.email == body.email.lower()))
    user = result.scalar_one_or_none()

    if not user or not verify_password(body.password, user.hashed_password):
        await _write_audit(
            db, action="login_failed", details={"email": body.email},
            ip=ip, success=False, error="invalid credentials"
        )
        await _record_failed_login(email, ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_GENERIC_LOGIN_FAIL,
        )

    if password_needs_upgrade(user.hashed_password):
        user.hashed_password = hash_password(body.password)
        await db.flush()

    if not _login_allowed(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Нет доступа к платформе. Обратитесь к администратору.",
        )

    if user.must_change_password:
        return TokenResponse(must_change_password=True)

    if user_needs_verification(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email verification required. Check your inbox or request a new verification link.",
        )

    has_webauthn = await webauthn_service.has_credential(db, user.id)
    if has_webauthn:
        if not body.webauthn_credential:
            return TokenResponse(webauthn_required=True)
        try:
            await webauthn_service.verify_assertion(db, user.id, body.webauthn_credential)
        except ValueError as exc:
            logger.warning("webauthn assertion failed", error=str(exc))
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=_client_error_detail(exc, fallback=_GENERIC_WEBAUTHN_FAIL),
            ) from exc

    role = map_legacy_user_role(user.role.value if hasattr(user.role, "value") else str(user.role))
    is_admin = has_permission(role, "*")

    if bool(getattr(user, "two_factor_enabled", False)) and user.two_factor_secret:
        pending_id = new_uuid()
        pending_jwt = create_access_token(
            user.email,
            extra_claims={"purpose": "2fa_pending", "pending_id": pending_id, "uid": user.id},
            expires_delta=timedelta(minutes=5),
        )
        await store_pending_login(
            pending_id,
            {
                "user_id": user.id,
                "email": user.email,
                "ip": ip,
                "fingerprint": body.fingerprint,
                "user_agent": body.user_agent or request.headers.get("user-agent"),
            },
        )
        await _write_audit(
            db,
            action="login_2fa_challenge",
            user_id=user.id,
            ip=ip,
            details={"pending_id": pending_id},
        )
        return TokenResponse(
            two_factor_required=True,
            two_factor_pending_token=pending_jwt,
            two_factor_backup_allowed=True,
        )

    extra = {
        "is_admin": is_admin,
        "role": user.role.value if hasattr(user.role, "value") else str(user.role),
        "user_id": user.id,
    }
    if bool(getattr(user, "two_factor_enabled", False)):
        extra["amr"] = ["pwd", "otp"]
    extra["pv"] = phone_claim(user)
    access = create_access_token(user.email, extra_claims=extra)
    refresh, family_id, jti = create_refresh_token(user.email)
    await register_refresh_family(db, user.email, family_id, jti)

    if body.fingerprint:
        device = await device_identity_service.fingerprint_device(
            db,
            fingerprint_raw=body.fingerprint,
            ip=ip,
            user_agent=body.user_agent or request.headers.get("user-agent"),
        )
        trust = await device_identity_service.resolve_effective_trust(
            db, user.email, device_id=device.id
        )
        try:
            await device_identity_service.register_device_for_user(
                db,
                user.id,
                device,
                trust_level=trust,
                is_new_binding=False,
                privileged_login=trust.value == "privileged",
                actor_user_id=user.id,
            )
        except ValueError as exc:
            logger.warning("device binding failed on login", error=str(exc))
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=_client_error_detail(exc, fallback=_GENERIC_DEVICE_FAIL),
            ) from exc
        if trust == TrustLevel.PRIVILEGED:
            identity = await get_identity_for_email(db, user.email)
            if identity is not None and identity.trust_level != TrustLevel.PRIVILEGED.value:
                identity.trust_level = TrustLevel.PRIVILEGED.value

    user.last_login = datetime.now(timezone.utc)
    if user.trial_started_at is None:
        user.trial_started_at = datetime.now(timezone.utc)
        await paywall_subscription_service.start_trial_on_first_login(db, user.id)
    await db.commit()

    await rate_limit_clear(_login_rate_limit_key(email, ip))
    await rate_limit_clear(_login_rate_limit_email_key(email))

    await _write_audit(db, action="login_success", user_id=user.id, ip=ip)
    logger.info("User logged in", email=user.email)

    enrollment_required = is_admin and not bool(getattr(user, "two_factor_enabled", False))
    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        two_factor_enrollment_required=enrollment_required,
    )


@router.post("/login/verify-2fa", response_model=TokenResponse)
async def login_verify_2fa(
    body: TwoFactorLoginVerifyIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Complete login after password (+ WebAuthn) with TOTP or backup code."""
    ip = get_client_ip(request)
    try:
        payload = decode_token(body.pending_token)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Сессия 2FA истекла. Войдите снова.") from exc
    if payload.get("purpose") != "2fa_pending" or payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Неверный токен 2FA")
    pending_id = str(payload.get("pending_id") or "")
    email = str(payload.get("sub") or "").lower()
    pending = await load_pending_login(pending_id) if pending_id else None
    if not pending or str(pending.get("email", "")).lower() != email:
        # Redis miss: trust short-lived 2fa_pending JWT (5 min) so Redis blip ≠ login break.
        uid = payload.get("uid")
        if uid and email:
            pending = {
                "user_id": uid,
                "email": email,
                "ip": get_client_ip(request),
                "fingerprint": None,
                "user_agent": request.headers.get("user-agent"),
                "jwt_fallback": True,
            }
        else:
            raise HTTPException(status_code=401, detail="Сессия 2FA истекла. Войдите снова.")

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None or not user.two_factor_enabled or not user.two_factor_secret:
        raise HTTPException(status_code=401, detail="2FA недоступна для этого пользователя")

    allowed, _, retry_after = await rate_limit_peek(
        verify_fail_key(user.id), VERIFY_MAX_FAILURES, fail_closed=True
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Слишком много попыток. Повторите через {retry_after or VERIFY_LOCK_WINDOW_SEC} сек.",
        )

    ok = False
    used_backup = False
    if body.code:
        ok = verify_totp(decrypt_totp_secret(user.two_factor_secret), body.code)
    if not ok and body.backup_code:
        ok, remaining = consume_backup_code(user.two_factor_backup_codes, body.backup_code)
        if ok:
            used_backup = True
            user.two_factor_backup_codes = remaining
            await db.flush()

    if not ok:
        await rate_limit_record_failure(
            verify_fail_key(user.id),
            VERIFY_MAX_FAILURES,
            VERIFY_LOCK_WINDOW_SEC,
            fail_closed=True,
        )
        await _write_audit(
            db,
            action="login_2fa_failed",
            user_id=user.id,
            ip=ip,
            success=False,
            error="invalid_code",
        )
        raise HTTPException(status_code=401, detail="Неверный код 2FA или резервный код")

    await clear_pending_login(pending_id)
    await rate_limit_clear(verify_fail_key(user.id))

    if not _login_allowed(user):
        raise HTTPException(status_code=403, detail="Нет доступа к платформе.")
    if user_needs_verification(user):
        raise HTTPException(status_code=403, detail="Email verification required.")

    role = map_legacy_user_role(user.role.value if hasattr(user.role, "value") else str(user.role))
    extra = {
        "is_admin": has_permission(role, "*"),
        "role": user.role.value if hasattr(user.role, "value") else str(user.role),
        "amr": ["pwd", "otp"],
        "user_id": user.id,
    }
    extra["pv"] = phone_claim(user)
    access = create_access_token(user.email, extra_claims=extra)
    refresh, family_id, jti = create_refresh_token(user.email)
    await register_refresh_family(db, user.email, family_id, jti)

    fp = pending.get("fingerprint")
    if fp:
        device = await device_identity_service.fingerprint_device(
            db,
            fingerprint_raw=str(fp),
            ip=ip,
            user_agent=pending.get("user_agent") or request.headers.get("user-agent"),
        )
        trust = await device_identity_service.resolve_effective_trust(
            db, user.email, device_id=device.id
        )
        try:
            await device_identity_service.register_device_for_user(
                db,
                user.id,
                device,
                trust_level=trust,
                is_new_binding=False,
                privileged_login=trust.value == "privileged",
                actor_user_id=user.id,
            )
        except ValueError as exc:
            logger.warning("device binding failed on 2fa login", error=str(exc))
            raise HTTPException(
                status_code=403,
                detail=_client_error_detail(exc, fallback=_GENERIC_DEVICE_FAIL),
            ) from exc

    user.last_login = datetime.now(timezone.utc)
    if user.trial_started_at is None:
        user.trial_started_at = datetime.now(timezone.utc)
        await paywall_subscription_service.start_trial_on_first_login(db, user.id)
    await db.commit()

    await _write_audit(
        db,
        action="login_2fa_success" if not used_backup else "login_2fa_backup_used",
        user_id=user.id,
        ip=ip,
        details={"backup": used_backup},
    )
    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(body: RefreshRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    """Exchange a refresh token for a new access + refresh pair with rotation."""
    try:
        payload = decode_token(body.refresh_token)
        if payload.get("type") != "refresh":
            raise ValueError("Not a refresh token")
        email = payload["sub"]
        family_id = payload.get("family_id")
        jti = payload.get("jti")
        if not family_id or not jti:
            raise ValueError("Legacy refresh token — login again")
    except (JWTError, ValueError, KeyError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        ) from exc

    try:
        refresh, _new_jti = await rotate_refresh_token(
            db,
            subject=email,
            family_id=family_id,
            presented_jti=jti,
        )
    except ValueError as exc:
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc

    result = await db.execute(select(User).where(User.email == email.lower()))
    user = result.scalar_one_or_none()
    denied = _session_denied_detail(user)
    if denied:
        await revoke_all_refresh_families(db, email)
        await db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=denied)

    role = map_legacy_user_role(
        user.role.value if hasattr(user.role, "value") else str(user.role)
    )
    extra = {
        "is_admin": has_permission(role, "*"),
        "role": user.role.value if hasattr(user.role, "value") else str(user.role),
        "user_id": user.id,
    }
    extra["pv"] = phone_claim(user)
    access = create_access_token(email, extra_claims=extra)
    await db.commit()

    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/logout")
async def logout(
    payload: dict = Depends(get_current_user_payload),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Revoke this access token and every refresh family for the session."""
    jti = payload.get("jti")
    if isinstance(jti, str) and jti:
        revoke_access_jti(jti)
    email = payload.get("sub")
    if isinstance(email, str) and email:
        await revoke_all_refresh_families(db, email)
        await db.commit()
    return {"ok": True}


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    body: UserCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Register a new user on trial; full access waits for admissions approval."""
    if not _registration_allowed(body.email):
        from app.services.legal.gates import CLOSED_REASON

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Регистрация {CLOSED_REASON}.",
        )
    if not (body.accept_terms and body.consent_pd):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Чтобы зарегистрироваться, примите пользовательское соглашение и дайте согласие на обработку персональных данных.",
        )
    ip = get_client_ip(request) or "0.0.0.0"
    email = body.email.lower().strip()
    await _require_bot_check(body.turnstile_token, ip)

    register_cap = 100 if settings.QA_E2E_DEMO else 5
    allowed, _remaining = await rate_limit_check(
        f"register:{ip}", register_cap, 3600, fail_closed=True
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Слишком много попыток регистрации. Повторите позже.",
        )

    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    confirmed_phone = None
    if settings.PHONE_SIGNIN_REQUIRED and not settings.QA_E2E_DEMO:
        from app.services.auth.phone import PhoneError, check_code

        if not body.phone or not body.phone_code:
            raise HTTPException(status_code=422, detail="Подтвердите номер телефона кодом из СМС.")
        try:
            confirmed_phone = await check_code(body.phone, body.phone_code)
        except PhoneError as exc:
            raise HTTPException(status_code=exc.status, detail=exc.message) from exc
        taken = await db.execute(select(User.id).where(User.phone_hash == confirmed_phone.hash))
        if taken.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Этот номер уже привязан к другому аккаунту.")

    if not settings.QA_E2E_DEMO:
        abuse = await score_signup_abuse_async(
            db,
            email=email,
            ip_range=ip_range_key(ip),
            proxy_risk=0.0,
            timezone_mismatch=body.timezone_mismatch,
            phone=getattr(body, "contact_phone", None),
        )
        if abuse.decision_hint == "block":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Registration blocked due to abuse signals. Contact support.",
            )

    user = User(
        email=email,
        hashed_password=hash_password(body.password),
        role=UserRole.VIEWER,
        is_active=True,
        is_whitelisted=True,
        trial_started_at=datetime.now(timezone.utc),
    )
    if confirmed_phone is not None:
        user.phone_hash = confirmed_phone.hash
        user.phone_last4 = confirmed_phone.last4
        user.phone_verified_at = datetime.now(timezone.utc)
    db.add(user)
    await db.flush()
    from app.services.legal.acceptance import record_registration_consents

    await record_registration_consents(
        db,
        user.id,
        ip=ip,
        user_agent=body.user_agent or request.headers.get("user-agent"),
    )

    existing_case = await admissions_service.find_latest_case_by_email(db, email)
    lead_notes = (body.notes or "").strip() or "Самостоятельная регистрация, пробный период до одобрения полного доступа"
    if existing_case:
        await admissions_service.attach_user_to_case(
            db,
            existing_case,
            user.id,
            note=lead_notes,
        )
        case = existing_case
    else:
        case = await admissions_service.create_lead(
            db,
            AdmissionCaseCreate(
                contact_email=email,
                contact_name=body.contact_name,
                contact_phone=body.contact_phone,
                source="self_signup",
                jurisdiction=body.jurisdiction,
                capital_range=body.capital_range,
                experience_level=body.experience_level,
                strategy_interest=body.strategy_interest,
                user_id=user.id,
                notes=lead_notes,
            ),
            actor_user_id=None,
        )
    extra = dict(case.extra or {})
    extra["trial_used"] = True
    extra["has_platform_account"] = True
    case.extra = extra
    await db.flush()
    if case.status == AdmissionStatus.LEAD.value:
        await admissions_service.change_status(
            db,
            case.id,
            AdmissionStatus.TRIAL,
            reason="self_signup_trial",
        )

    await access_policy_service.start_trial(db, user.id)
    await paywall_subscription_service.start_trial_on_first_login(db, user.id)

    if not settings.QA_E2E_DEMO:
        from app.services.settings.new_user_defaults import seed_new_user_settings

        await seed_new_user_settings(db, email)
        await send_verification_email_for_user(
            db,
            user,
            ip=ip,
            user_agent=body.user_agent or request.headers.get("user-agent"),
        )
    else:
        user.email_verified_at = datetime.now(timezone.utc)
        await db.flush()

    await db.commit()
    await db.refresh(user)

    await _write_audit(
        db,
        action="register_success",
        user_id=user.id,
        ip=ip,
        details={
            "abuse_risk_score": 0 if settings.QA_E2E_DEMO else abuse.risk_score,
            "decision_hint": "allow" if settings.QA_E2E_DEMO else abuse.decision_hint,
            "trial": True,
        },
    )
    logger.info(
        "New user registered on trial",
        email=user.email,
        abuse_hint="allow" if settings.QA_E2E_DEMO else abuse.decision_hint,
    )
    from app.services.product_analytics.hooks import emit_server_event

    emit_server_event("registration", subject=str(user.id))

    if user_needs_verification(user):
        return TokenResponse(
            pending_approval=True,
            email_verification_required=True,
        )

    role = map_legacy_user_role(user.role.value if hasattr(user.role, "value") else str(user.role))
    extra_claims = {
        "is_admin": has_permission(role, "*"),
        "role": user.role.value if hasattr(user.role, "value") else str(user.role),
        "user_id": user.id,
    }
    extra_claims["pv"] = phone_claim(user)
    access = create_access_token(user.email, extra_claims=extra_claims)
    refresh, family_id, jti = create_refresh_token(user.email)
    await register_refresh_family(db, user.email, family_id, jti)
    await db.commit()

    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        pending_approval=True,
    )


@router.post("/change-password")
async def change_password(
    body: ChangePasswordIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Force password change on first login — verified by current password, no JWT required."""
    ip = get_client_ip(request)
    email = body.email.lower().strip()
    await _enforce_login_rate_limit(email, ip)

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    invalid = (
        user is None
        or not user.must_change_password
        or not verify_password(body.current_password, user.hashed_password)
    )
    if invalid:
        await _record_failed_login(email, ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    user.hashed_password = hash_password(body.new_password)
    user.must_change_password = False
    await db.commit()
    await rate_limit_clear(_login_rate_limit_key(email, ip))
    await rate_limit_clear(_login_rate_limit_email_key(email))
    has_webauthn = await webauthn_service.has_credential(db, user.id)
    return {
        "ok": True,
        "webauthn_registration_required": not has_webauthn,
    }


@router.post("/password-change/request")
async def password_change_request(
    body: PasswordChangeRequestIn,
    request: Request,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
):
    """Start email-confirmed password change for the authenticated user."""
    ip = get_client_ip(request)
    allowed, _ = await rate_limit_check(f"pwd_change:{email}", 5, 3600, fail_closed=True)
    if not allowed:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many password change requests")

    result = await db.execute(select(User).where(User.email == email.lower()))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    try:
        dev_code = await request_password_change(user.id, user.email, body.new_password)
    except RuntimeError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Отправка email временно недоступна. Обратитесь в поддержку.",
        ) from exc
    await _write_audit(db, action="password_change_requested", user_id=user.id, ip=ip)
    out: dict = {"ok": True, "message": "Confirmation code sent to your email on file"}
    if settings.is_development and dev_code:
        out["dev_code"] = dev_code
    return out


@router.post("/password-change/confirm")
async def password_change_confirm(
    body: PasswordChangeConfirmIn,
    request: Request,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
):
    """Confirm password change with email OTP or magic link token."""
    ip = get_client_ip(request)
    allowed, _ = await rate_limit_check(
        f"pwd_change_confirm:{email}", 8, 900, fail_closed=True
    )
    if not allowed:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many confirmation attempts")
    result = await db.execute(select(User).where(User.email == email.lower()))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    ok = await confirm_password_change(
        user.id,
        code=body.code,
        token=body.token,
        new_password=body.new_password,
    )
    if not ok:
        await _write_audit(
            db,
            action="password_change_failed",
            user_id=user.id,
            ip=ip,
            success=False,
            error="invalid token or code",
        )
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired confirmation code")

    user.hashed_password = apply_new_password_hash(body.new_password)
    user.must_change_password = False
    await revoke_all_refresh_families(db, user.email)
    await db.commit()
    await _write_audit(db, action="password_change_confirmed", user_id=user.id, ip=ip)
    return {"ok": True, "message": "Password updated. Please sign in again."}


@router.post("/recover", response_model=RecoverPasswordOut)
async def recover_password(
    body: RecoverPasswordIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> RecoverPasswordOut:
    """Request password reset — always returns generic response."""
    ip = get_client_ip(request)
    ua = request.headers.get("user-agent")
    result = await request_password_recovery(
        db,
        email=body.email,
        ip=ip,
        user_agent=ua,
    )
    await db.commit()
    return RecoverPasswordOut(**result)


@router.post("/reset")
async def reset_password(
    body: ResetPasswordIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Consume recovery token and set new password."""
    ip = get_client_ip(request)
    allowed, _ = await rate_limit_check(
        f"reset_pw:{ip or 'unknown'}", 10, 3600, fail_closed=True
    )
    if not allowed:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many reset attempts")
    ua = request.headers.get("user-agent")
    ok = await reset_password_with_token(
        db,
        raw_token=body.token,
        new_password=body.new_password,
        ip=ip,
        user_agent=ua,
    )
    if not ok:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired reset token")
    await db.commit()
    return {"ok": True, "message": "Password reset successful. Please sign in."}


@router.post("/wasnt-me")
async def report_unauthorized_reset(
    body: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """One-click 'this wasn't me' from password-changed email — revoke all sessions."""
    raw_token = str(body.get("token") or "").strip()
    if not raw_token:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Missing token")
    ip = get_client_ip(request)
    ua = request.headers.get("user-agent")
    ok = await report_unauthorized_password_change(
        db,
        raw_token=raw_token,
        ip=ip,
        user_agent=ua,
    )
    if not ok:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired security link")
    await db.commit()
    return {
        "ok": True,
        "message": "All sessions revoked. Account flagged for review. Contact support if needed.",
    }


@router.post("/verify-email/request", response_model=GenericMessageOut)
async def verify_email_request(
    body: VerifyEmailRequestIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> GenericMessageOut:
    ip = get_client_ip(request)
    ua = request.headers.get("user-agent")
    result = await resend_verification_email(
        db,
        email=body.email,
        ip=ip,
        user_agent=ua,
    )
    await db.commit()
    return GenericMessageOut(**result)


@router.post("/verify-email/confirm")
async def verify_email_confirm(
    body: VerifyEmailConfirmIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    ip = get_client_ip(request)
    ua = request.headers.get("user-agent")
    ok = await confirm_email_verification(
        db,
        raw_token=body.token,
        ip=ip,
        user_agent=ua,
    )
    if not ok:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired verification token")
    await db.commit()
    return {"ok": True, "message": "Email verified successfully."}


@router.post("/webauthn/register/options")
async def webauthn_register_options(
    body: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    email = str(body.get("email") or "").lower()
    password = str(body.get("password") or "")
    ip = get_client_ip(request)
    await _enforce_login_rate_limit(email, ip)
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(password, user.hashed_password):
        await _record_failed_login(email, ip)
        raise HTTPException(401, "Invalid credentials")
    if user.must_change_password:
        raise HTTPException(403, "Change password first")
    return await webauthn_service.registration_options(db, user.id, email)


@router.post("/webauthn/register/verify")
async def webauthn_register_verify(
    body: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    email = str(body.get("email") or "").lower()
    password = str(body.get("password") or "")
    ip = get_client_ip(request)
    await _enforce_login_rate_limit(email, ip)
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(password, user.hashed_password):
        await _record_failed_login(email, ip)
        raise HTTPException(401, "Invalid credentials")
    credential = body.get("credential") or body
    try:
        await webauthn_service.verify_registration(db, user.id, credential)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await db.commit()
    return {"ok": True}


@router.post("/webauthn/login/options")
async def webauthn_login_options(
    body: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    email = str(body.get("email") or "").lower()
    ip = get_client_ip(request)
    allowed, _ = await rate_limit_check(
        f"webauthn_opts:{ip or 'unknown'}", 20, 300, fail_closed=True
    )
    if not allowed:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts")
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(400, "Unable to start passkey login")
    try:
        return await webauthn_service.assertion_options(db, user.id)
    except ValueError:
        raise HTTPException(400, "Unable to start passkey login")


@router.get("/me", response_model=UserOut)
async def get_me(
    payload: dict = Depends(get_current_user_payload),
    db: AsyncSession = Depends(get_db_after_auth),
) -> UserOut:
    """Get the currently authenticated user's profile."""
    result = await db.execute(select(User).where(User.email == payload["sub"]))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    out = UserOut.model_validate(user)
    out.phone_verified = bool(user.phone_verified_at)
    out.phone_last4 = user.phone_last4
    return out


class PhoneCodeIn(BaseModel):
    phone: str
    turnstile_token: str | None = None


class PhoneConfirmIn(BaseModel):
    phone: str
    code: str


@router.post("/phone/send-code")
async def phone_send_code(body: PhoneCodeIn, request: Request) -> dict:
    """Send a 6-digit code by SMS to a Russian mobile number (sign-up or confirmation)."""
    from app.services.auth.phone import PhoneError, send_code

    ip = get_client_ip(request) or "0.0.0.0"
    await _require_bot_check(body.turnstile_token, ip)
    try:
        return await send_code(body.phone, ip=ip)
    except PhoneError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc


@router.post("/phone/confirm", response_model=TokenResponse)
async def phone_confirm(
    body: PhoneConfirmIn,
    payload: dict = Depends(get_current_user_payload),
    db: AsyncSession = Depends(get_db_after_auth),
) -> TokenResponse:
    """Attach a confirmed number to the signed-in account and re-issue the access token."""
    from app.services.auth.phone import PhoneError, check_code

    user = (await db.execute(select(User).where(User.email == payload["sub"]))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    try:
        phone = await check_code(body.phone, body.code)
    except PhoneError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc
    taken = await db.execute(select(User.id).where(User.phone_hash == phone.hash, User.id != user.id))
    if taken.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Этот номер уже привязан к другому аккаунту.")
    user.phone_hash = phone.hash
    user.phone_last4 = phone.last4
    user.phone_verified_at = datetime.now(timezone.utc)
    await db.commit()
    claims = {k: v for k, v in payload.items() if k not in {"sub", "exp", "iat", "type", "jti", "nbf"}}
    claims["pv"] = True
    access = create_access_token(user.email, extra_claims=claims)
    return TokenResponse(access_token=access, expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60)


@router.post("/admin/whitelist", status_code=status.HTTP_200_OK)
async def add_to_whitelist(
    email: str,
    _: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Admin: add an email to the whitelist and activate existing user if present."""
    result = await db.execute(select(User).where(User.email == email.lower()))
    user = result.scalar_one_or_none()
    if user:
        user.is_whitelisted = True
        await db.commit()
        return {"message": f"{email} whitelisted", "existing_user": True}

    return {"message": f"{email} will be whitelisted on registration", "existing_user": False}
