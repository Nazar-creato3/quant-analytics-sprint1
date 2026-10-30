"""API: devices, access policy, admin MFA, subscriptions, sub-portfolios, security audit."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.client_ip import get_client_ip
from app.core.config import settings
from app.core.deps import get_current_user_email, get_db, require_admin_mfa
from app.core.rbac_deps import get_user_and_role
from app.core.security import create_admin_access_token
from app.db.models import AuditLog, User
from app.domain.access_policy import AccessLevel, is_full_access_level
from app.domain.admin_security import (
    BreakGlassRequestORM,
    admin_path_allowed_for_role,
    generate_totp_secret,
    requires_reauth,
    verify_totp,
)
from app.domain.device_identity import DeviceFingerprintIn, DeviceFingerprintOut
from app.domain.rbac import IdentityORM, SystemRole, TrustLevel, has_permission, trust_level_for_role
from app.domain.sub_portfolio import (
    SubPortfolioCreate,
    SubPortfolioORM,
    SubPortfolioRead,
    diversification_score,
    rebalance_subportfolios_plan,
)
from app.domain.application_flow import PaymentWebhookIn
from app.domain.subscription import (
    PaymentWebhookStub,
    SubscriptionCreate,
    SubscriptionORM,
    subscription_service,
)
from app.services.admissions.service import admissions_service
from app.services.billing.yookassa import (
    checkout_configured,
    create_checkout,
    fetch_succeeded_payment_user_id,
)
from app.services.subscription.paywall import paywall_subscription_service
from app.services.webauthn.service import webauthn_service
import hashlib
import hmac
from app.services.access_policy.service import access_policy_service
from app.services.device_identity.service import device_identity_service
from app.services.device_trust.policy import policy_for_trust_level
from app.services.signup_abuse.guard import score_signup_abuse_async
from app.utils.audit import AuditAction, audit
from app.utils.cache import rate_limit_check
from app.utils.helpers import new_uuid, utcnow

devices_router = APIRouter(prefix="/devices", tags=["devices"])
access_router = APIRouter(prefix="/access-policy", tags=["access-policy"])
admin_router = APIRouter(prefix="/admin", tags=["admin-security"])
billing_router = APIRouter(prefix="/billing", tags=["billing"])
subport_router = APIRouter(prefix="/sub-portfolios", tags=["sub-portfolios"])


async def _user(db: AsyncSession, email: str) -> User:
    user, _role = await get_user_and_role(db, email)
    return user


@devices_router.post("/fingerprint", response_model=DeviceFingerprintOut)
async def register_fingerprint(
    body: DeviceFingerprintIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    email: str | None = None,
):
    # Optional auth: try header silently via dependency alternative
    ip = get_client_ip(request)
    device = await device_identity_service.fingerprint_device(
        db,
        fingerprint_raw=body.fingerprint,
        ip=ip,
        user_agent=body.user_agent or request.headers.get("user-agent"),
    )
    cluster_id = await device_identity_service._cluster_id_for_device(db, device.id)
    # Bind if Authorization present — handled by separate bind endpoint
    await db.commit()
    return DeviceFingerprintOut(
        device_id=device.id,
        fingerprint_hash=device.fingerprint_hash,
        cluster_id=cluster_id,
    )


@devices_router.post("/bind")
async def bind_device(
    body: DeviceFingerprintIn,
    request: Request,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
):
    user = await _user(db, email)
    device = await device_identity_service.fingerprint_device(
        db,
        fingerprint_raw=body.fingerprint,
        ip=get_client_ip(request),
        user_agent=body.user_agent or request.headers.get("user-agent"),
    )
    trust = await device_identity_service.resolve_effective_trust(
        db, email, device_id=device.id
    )
    try:
        await device_identity_service.register_device_for_user(
            db,
            user.id,
            device,
            trust_level=trust,
            privileged_login=trust == TrustLevel.PRIVILEGED,
            actor_user_id=user.id,
        )
    except ValueError as exc:
        raise HTTPException(403, str(exc)) from exc
    await db.commit()
    return {"ok": True, "device_id": device.id}


@access_router.get("/me")
async def my_access(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
):
    user = await _user(db, email)
    payload = (await access_policy_service.read(db, user.id)).model_dump(mode="json")
    payload.update(await paywall_subscription_service.snapshot(db, user.id))
    if payload.get("paid") or is_full_access_level(str(payload.get("access_level") or "")):
        payload["show_trial_timer"] = False
        payload["trial_remaining_seconds"] = 0
        payload["trial_expires_at"] = None
    payload["checkout_configured"] = checkout_configured()
    payload["subscription_amount_rub"] = settings.SUBSCRIPTION_AMOUNT_RUB
    return payload


@access_router.post("/signup-risk")
async def signup_risk_preview(payload: dict, request: Request, db: AsyncSession = Depends(get_db)):
    ip = get_client_ip(request) or "0.0.0.0"
    allowed, _ = await rate_limit_check(f"signup_risk:{ip}", 20, 3600, fail_closed=True)
    if not allowed:
        raise HTTPException(429, "Too many requests")
    email = str(payload.get("email") or "")
    from app.domain.device_identity import ip_range_key

    result = await score_signup_abuse_async(
        db,
        email=email,
        ip_range=ip_range_key(ip),
        proxy_risk=float(payload.get("proxy_risk") or 0),
        timezone_mismatch=bool(payload.get("timezone_mismatch")),
        phone=str(payload.get("phone") or "") or None,
        payment_instrument_hash=str(payload.get("payment_instrument_hash") or "") or None,
    )
    return {
        "risk_score": result.risk_score,
        "decision_hint": result.decision_hint,
        "details": result.signals.details,
    }


@admin_router.post("/login/check")
async def admin_login_check(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
):
    """Separate admin contour gate — user login alone is insufficient without role."""
    user, role = await get_user_and_role(db, email)
    from app.domain.admin_security import admin_path_allowed_for_role

    if not admin_path_allowed_for_role(role):
        raise HTTPException(403, "Admin path denied for this identity")
    result = await db.execute(select(IdentityORM).where(IdentityORM.primary_email == email))
    identity = result.scalar_one_or_none()
    if identity is None:
        identity = IdentityORM(
            id=new_uuid(),
            primary_email=email,
            trust_level=trust_level_for_role(role).value,
            system_role=role.value,
            user_id=user.id,
            mfa_enabled=False,
        )
        db.add(identity)
        await audit.log(
            db,
            action=AuditAction.ROLE_ASSIGNED,
            user_id=user.id,
            resource_type="identity",
            resource_id=identity.id,
            details={"system_role": role.value, "source": "admin_login_check"},
        )
        await db.commit()
        await db.refresh(identity)
    return {
        "ok": True,
        "identity_id": identity.id,
        "system_role": identity.system_role,
        "mfa_enabled": identity.mfa_enabled,
        "mfa_required": True,
    }


@admin_router.post("/mfa/setup")
async def mfa_setup(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
):
    user, role = await get_user_and_role(db, email)
    from app.domain.admin_security import admin_path_allowed_for_role

    if not admin_path_allowed_for_role(role):
        raise HTTPException(403, "Admin only")
    result = await db.execute(select(IdentityORM).where(IdentityORM.primary_email == email))
    identity = result.scalar_one_or_none()
    if not identity:
        raise HTTPException(404, "Identity missing — call /admin/login/check first")
    secret = generate_totp_secret()
    identity.mfa_secret = secret
    identity.mfa_enabled = False
    await db.commit()
    return {"secret": secret, "otpauth_hint": f"otpauth://totp/ApexAdmin:{email}?secret={secret}&issuer=ApexIntel"}


@admin_router.post("/mfa/verify")
async def mfa_verify(
    body: dict,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(IdentityORM).where(IdentityORM.primary_email == email))
    identity = result.scalar_one_or_none()
    if not identity or not identity.mfa_secret:
        raise HTTPException(400, "MFA not set up")
    code = str(body.get("code") or "")
    if not verify_totp(identity.mfa_secret, code):
        raise HTTPException(401, "Invalid MFA code")
    identity.mfa_enabled = True
    await audit.log(
        db,
        action="admin_mfa_verified",
        user_id=identity.user_id,
        resource_type="identity",
        resource_id=identity.id,
        details={},
    )
    await db.commit()
    admin_token = create_admin_access_token(
        email,
        extra_claims={"identity_id": identity.id, "system_role": identity.system_role},
    )
    return {
        "ok": True,
        "mfa_enabled": True,
        "admin_access_token": admin_token,
        "token_type": "bearer",
        "audience": settings.ADMIN_TOKEN_AUDIENCE,
        "cookie_name": settings.ADMIN_ACCESS_TOKEN_COOKIE,
    }


@admin_router.post("/break-glass")
async def break_glass_create(
    body: dict,
    identity: IdentityORM = Depends(require_admin_mfa),
    db: AsyncSession = Depends(get_db),
):
    if not has_permission(SystemRole(identity.system_role), "*"):
        raise HTTPException(403, "owner_admin only")
    if requires_reauth("break_glass.approve"):
        pass
    user = await _user(db, identity.primary_email)
    reason = str(body.get("reason") or "").strip()
    if len(reason) < 5:
        raise HTTPException(400, "reason required")
    req = BreakGlassRequestORM(
        id=new_uuid(),
        requester_identity_id=identity.id,
        reason=reason,
        approvals_needed=2,
    )
    db.add(req)
    await audit.log(
        db,
        action="break_glass_triggered",
        user_id=user.id,
        resource_type="break_glass",
        resource_id=req.id,
        details={"reason": reason},
    )
    await db.commit()
    return {"id": req.id, "status": req.status, "approvals_needed": req.approvals_needed}


@admin_router.post("/break-glass/{request_id}/approve")
async def break_glass_approve(
    request_id: str,
    identity: IdentityORM = Depends(require_admin_mfa),
    db: AsyncSession = Depends(get_db),
):
    if requires_reauth("break_glass.approve"):
        pass
    user = await _user(db, identity.primary_email)
    role = SystemRole(identity.system_role)
    if not has_permission(role, "*"):
        raise HTTPException(403, "owner_admin approval required")
    result = await db.execute(
        select(BreakGlassRequestORM).where(BreakGlassRequestORM.id == request_id)
    )
    req = result.scalar_one_or_none()
    if not req or req.status != "pending":
        raise HTTPException(404, "Request not found")
    approved = [x for x in (req.approved_by or "").split(",") if x]
    if user.id in approved:
        raise HTTPException(400, "Already approved by you")
    approved.append(user.id)
    req.approved_by = ",".join(approved)
    req.approvals_count = len(approved)
    if req.approvals_count >= req.approvals_needed:
        req.status = "approved"
        req.resolved_at = utcnow()
    await db.commit()
    return {"id": req.id, "status": req.status, "approvals_count": req.approvals_count}


@admin_router.get("/security-audit")
async def security_audit(
    identity: IdentityORM = Depends(require_admin_mfa),
    db: AsyncSession = Depends(get_db),
    actor: str | None = Query(default=None, description="Filter by user_id"),
    action: str | None = Query(default=None, description="Filter by action"),
    from_date: datetime | None = Query(default=None, alias="from"),
    to_date: datetime | None = Query(default=None, alias="to"),
):
    """Prompt 64 — owner_admin Security & Audit view with filters."""
    role = SystemRole(identity.system_role)
    if not has_permission(role, "*"):
        raise HTTPException(403, "owner_admin only")

    SECURITY_ACTIONS = (
        AuditAction.ROLE_ASSIGNED,
        AuditAction.ROLE_REVOKED,
        AuditAction.PERMISSION_CHANGED,
        AuditAction.DEVICE_REGISTERED,
        AuditAction.DEVICE_REVOKED,
        AuditAction.DEVICE_OVERRIDE,
        AuditAction.TRIAL_DENIED_DUPLICATE,
        AuditAction.ACCOUNT_CLUSTER_MERGED,
        AuditAction.BREAK_GLASS_TRIGGERED,
        AuditAction.ADMIN_MFA_VERIFIED,
        AuditAction.MFA_DISABLED,
        "privileged_login",
        "admission_escalated",
    )
    q = select(AuditLog).where(AuditLog.action.in_(SECURITY_ACTIONS))
    if actor:
        q = q.where(AuditLog.user_id == actor)
    if action:
        q = q.where(AuditLog.action == action)
    if from_date:
        q = q.where(AuditLog.timestamp >= from_date)
    if to_date:
        q = q.where(AuditLog.timestamp <= to_date)
    q = q.order_by(AuditLog.timestamp.desc()).limit(200)
    result = await db.execute(q)
    rows = result.scalars().all()
    return {
        "items": [
            {
                "id": r.id,
                "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                "action": r.action,
                "user_id": r.user_id,
                "resource_type": r.resource_type,
                "resource_id": r.resource_id,
                "details": r.details,
            }
            for r in rows
        ]
    }


@admin_router.post("/device-policy/evaluate")
async def evaluate_device_policy(
    body: dict,
    _identity: IdentityORM = Depends(require_admin_mfa),
):
    trust = body.get("trust_level") or TrustLevel.STANDARD.value
    decision = policy_for_trust_level(trust).evaluate(
        active_devices=int(body.get("active_devices") or 1),
        accounts_on_device=int(body.get("accounts_on_device") or 1),
        is_new_account_on_device=bool(body.get("is_new_account_on_device")),
    )
    return {
        "allowed": decision.allowed,
        "reason": decision.reason,
        "require_manual_review": decision.require_manual_review,
    }


@admin_router.post("/users/{user_id}/release-device")
async def release_device_binding(
    user_id: str,
    identity: IdentityORM = Depends(require_admin_mfa),
    db: AsyncSession = Depends(get_db),
):
    """Admin-only: release WebAuthn device binding with audit log."""
    role = SystemRole(identity.system_role)
    if not has_permission(role, "*"):
        raise HTTPException(403, "owner_admin only")
    admin_user = await _user(db, identity.primary_email)
    await webauthn_service.release_device_binding(
        db, user_id, actor_user_id=admin_user.id
    )
    await db.commit()
    return {"ok": True, "user_id": user_id}


@billing_router.post("/webhook/payment")
async def payment_webhook(body: PaymentWebhookIn, db: AsyncSession = Depends(get_db)):
    """Verified payment webhook — only path to subscription_status=paid."""
    secret = settings.PAYMENT_WEBHOOK_SECRET
    if not secret:
        raise HTTPException(503, "Payment webhook not configured")
    expected = hmac.new(
        secret.encode(),
        f"{body.event}:{body.user_id}:{body.external_ref or ''}".encode(),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, body.signature):
        raise HTTPException(401, "Invalid webhook signature")
    if body.event != "payment_succeeded":
        raise HTTPException(400, "Unsupported event")
    await admissions_service.grant_full_access(
        db, body.user_id, external_ref=body.external_ref
    )
    await db.commit()
    return {"ok": True, "user_id": body.user_id, "status": "paid"}


@billing_router.post("/checkout")
async def billing_checkout(
    request: Request,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
):
    user = await _user(db, email)
    ip = get_client_ip(request) if request is not None else "0.0.0.0"
    allowed, _ = await rate_limit_check(f"billing_checkout:{user.id}:{ip}", 8, 3600, fail_closed=True)
    if not allowed:
        raise HTTPException(429, "Too many checkout attempts")
    snap = await paywall_subscription_service.snapshot(db, user.id)
    if snap["paid"]:
        return {"already_paid": True, "checkout_url": None}
    from app.services.legal.gates import CLOSED_REASON, payment_open

    if not payment_open():
        raise HTTPException(403, f"Оплата {CLOSED_REASON}.")
    if not checkout_configured():
        raise HTTPException(503, "Оплата ещё не подключена. Напишите в поддержку.")
    try:
        return await create_checkout(user.id, user.email)
    except RuntimeError:
        raise HTTPException(502, "Не удалось создать счёт ЮKassa. Повторите позже.")


@billing_router.post("/webhook/yookassa")
async def yookassa_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """YooKassa notification: confirm payment via API, then grant full access."""
    if not checkout_configured():
        raise HTTPException(503, "YooKassa is not configured")
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(400, "Invalid JSON") from exc
    event = str(body.get("event") or "")
    payment_id = str((body.get("object") or {}).get("id") or "")
    if event != "payment.succeeded" or not payment_id:
        return {"ok": True, "ignored": True}
    user_id = await fetch_succeeded_payment_user_id(payment_id)
    if not user_id:
        raise HTTPException(401, "Payment not confirmed")
    await admissions_service.grant_full_access(db, user_id, external_ref=payment_id)
    await db.commit()
    return {"ok": True, "user_id": user_id, "status": "paid"}


@billing_router.post("/subscriptions")
async def create_subscription(
    body: SubscriptionCreate,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
):
    from app.services.legal.gates import payment_open

    user = await _user(db, email)
    if not payment_open():
        raise HTTPException(403, "Оплата недоступна.")
    try:
        sub = subscription_service.create_subscription(body, owner_profile_id=user.id)
    except PermissionError:
        raise HTTPException(403, "нет данных") from None
    db.add(sub)
    inv = subscription_service.create_invoice(sub)
    db.add(inv)
    await db.commit()
    return {
        "status": sub.status,
    }


@billing_router.post("/webhook/stub")
async def billing_webhook_stub(body: PaymentWebhookStub, db: AsyncSession = Depends(get_db)):
    """Disabled: stub must not grant live access. Real YooKassa webhook will replace this."""
    del body, db
    raise HTTPException(
        status_code=404,
        detail="Stub billing webhook is disabled. Full access is granted in Admissions.",
    )


@billing_router.post("/subscriptions/{subscription_id}/resume")
async def resume_subscription_access(
    subscription_id: str,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
):
    """Admin resume after dunning suspension (Prompt 59)."""
    _user, role = await get_user_and_role(db, email)
    if not has_permission(role, "billing.manage") and not has_permission(role, "*"):
        raise HTTPException(403, "billing.manage required")

    result = await db.execute(
        select(SubscriptionORM).where(SubscriptionORM.id == subscription_id)
    )
    sub = result.scalar_one_or_none()
    if not sub:
        raise HTTPException(404, "Subscription not found")

    subscription_service.resume_access(sub)
    await access_policy_service.set_level(
        db,
        sub.profile_id,
        subscription_service.access_level_for_tier(sub.tier),
        approved=True,
    )
    await audit.log(
        db,
        action="subscription_access_resumed",
        user_id=_user.id,
        resource_type="subscription",
        resource_id=sub.id,
        details={"profile_id": sub.profile_id},
    )
    await db.commit()
    return {"ok": True, "subscription_id": sub.id, "status": sub.status}


@subport_router.post("")
async def create_sub_portfolio(
    body: SubPortfolioCreate,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
):
    user = await _user(db, email)
    row = SubPortfolioORM(
        id=new_uuid(),
        profile_id=user.id,
        name=body.name,
        risk_budget=body.risk_budget,
        strategy_tags=body.strategy_tags,
        is_master=body.is_master,
        master_portfolio_id=body.master_portfolio_id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return SubPortfolioRead.model_validate(row)


@subport_router.get("/{profile_id}")
async def list_sub_portfolios(
    profile_id: str,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
):
    user = await _user(db, email)
    if user.id != profile_id:
        raise HTTPException(404, "Not found")
    result = await db.execute(
        select(SubPortfolioORM).where(SubPortfolioORM.profile_id == user.id)
    )
    rows = list(result.scalars().all())
    peer_tags = [list(r.strategy_tags or []) for r in rows]
    out = []
    for i, r in enumerate(rows):
        peers = peer_tags[:i] + peer_tags[i + 1 :]
        score = diversification_score(
            strategy_tags=list(r.strategy_tags or []),
            peer_tags=peers,
            risk_budget=r.risk_budget,
        )
        item = SubPortfolioRead.model_validate(r)
        item.diversification_score = score
        out.append(item)
    return {"items": out}


@subport_router.post("/{profile_id}/rebalance-plan")
async def rebalance_plan(
    profile_id: str,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
):
    user = await _user(db, email)
    if user.id != profile_id:
        raise HTTPException(404, "Not found")
    result = await db.execute(
        select(SubPortfolioORM).where(SubPortfolioORM.profile_id == user.id)
    )
    rows = list(result.scalars().all())
    plan = rebalance_subportfolios_plan(user.id, rows)
    return plan.model_dump()
