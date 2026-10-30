"""Application submission, approval, and credential issuance."""
from __future__ import annotations

import hashlib
import secrets
import string

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import hash_password
from app.db.models import User, UserRole
from app.domain.application_flow import (
    ApplicationORM,
    ApplicationStatus,
    ApplicationSubmitIn,
)
from app.services.application.disposable_email import is_disposable_email
from app.services.application.duplicate_detection import detect_duplicate_application
from app.services.application.email_verification import (
    generate_email_token,
    send_credentials_email,
    send_verification_email,
)
from app.services.application.phone_otp import verify_phone_otp
from app.services.application.turnstile import verify_turnstile
from app.utils.helpers import new_uuid, utcnow

logger = get_logger(__name__)


def hash_phone(phone: str) -> str:
    normalized = "".join(c for c in phone if c.isdigit())
    material = f"{normalized}:{settings.SECRET_KEY}"
    return hashlib.sha256(material.encode()).hexdigest()


def _extra_disposable_domains() -> frozenset[str]:
    raw = settings.DISPOSABLE_EMAIL_DOMAINS.strip()
    if not raw:
        return frozenset()
    return frozenset(d.strip().lower() for d in raw.split(",") if d.strip())


class ApplicationService:
    async def submit(
        self,
        db: AsyncSession,
        body: ApplicationSubmitIn,
        *,
        apply_ip: str | None,
    ) -> ApplicationORM:
        if not await verify_turnstile(body.turnstile_token, apply_ip):
            raise ValueError("turnstile_failed")

        email = str(body.email).strip().lower()
        if is_disposable_email(email, _extra_disposable_domains()):
            raise ValueError("disposable_email")

        phone_hash = hash_phone(body.phone)
        if not await verify_phone_otp(phone_hash, body.otp_code):
            raise ValueError("invalid_otp")

        is_dup, dup_reason = await detect_duplicate_application(
            db,
            email=email,
            name=body.name,
            phone=body.phone,
            phone_hash=phone_hash,
        )

        token = generate_email_token(email)
        app = ApplicationORM(
            id=new_uuid(),
            name=body.name,
            email=email,
            phone=body.phone.strip(),
            phone_hash=phone_hash,
            jurisdiction=body.jurisdiction,
            capital_range=body.capital_range,
            experience=body.experience,
            strategy_interest=body.strategy_interest,
            comments=body.comments,
            status=ApplicationStatus.PENDING_VERIFICATION.value,
            email_verification_token=token,
            phone_verified_at=utcnow(),
            duplicate_flag=is_dup,
            duplicate_reason=dup_reason,
            apply_ip=apply_ip,
        )
        db.add(app)
        await db.flush()
        await send_verification_email(email, token)
        return app

    async def verify_email(self, db: AsyncSession, token: str) -> ApplicationORM | None:
        result = await db.execute(
            select(ApplicationORM).where(ApplicationORM.email_verification_token == token)
        )
        app = result.scalar_one_or_none()
        if not app:
            return None
        if app.status != ApplicationStatus.PENDING_VERIFICATION.value:
            return app
        app.status = ApplicationStatus.PENDING_REVIEW.value
        app.email_verified_at = utcnow()
        app.email_verification_token = None
        app.updated_at = utcnow()
        await db.flush()
        return app

    async def approve(
        self,
        db: AsyncSession,
        application_id: str,
        *,
        actor_user_id: str | None = None,
        auto: bool = False,
    ) -> tuple[ApplicationORM, str]:
        """Issue credentials. Returns (application, plaintext_password). Password NEVER logged."""
        result = await db.execute(
            select(ApplicationORM).where(ApplicationORM.id == application_id)
        )
        app = result.scalar_one_or_none()
        if not app:
            raise LookupError("application_not_found")
        if app.status not in (
            ApplicationStatus.PENDING_REVIEW.value,
            ApplicationStatus.PENDING_VERIFICATION.value,
        ):
            raise ValueError(f"cannot_approve_status:{app.status}")

        existing = await db.execute(select(User).where(User.email == app.email))
        if existing.scalar_one_or_none():
            raise ValueError("email_already_registered")

        alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
        plaintext = "".join(secrets.choice(alphabet) for _ in range(20))

        user = User(
            email=app.email,
            hashed_password=hash_password(plaintext),
            role=UserRole.VIEWER,
            is_active=True,
            is_whitelisted=True,
            must_change_password=True,
        )
        db.add(user)
        await db.flush()

        app.status = ApplicationStatus.APPROVED.value
        app.user_id = user.id
        app.updated_at = utcnow()
        await db.flush()

        await send_credentials_email(app.email, plaintext)
        return app, plaintext

    async def reject(
        self,
        db: AsyncSession,
        application_id: str,
        reason: str,
    ) -> ApplicationORM:
        result = await db.execute(
            select(ApplicationORM).where(ApplicationORM.id == application_id)
        )
        app = result.scalar_one_or_none()
        if not app:
            raise LookupError("application_not_found")
        app.status = ApplicationStatus.REJECTED.value
        app.comments = f"{app.comments or ''}\n[reject] {reason}".strip()
        app.updated_at = utcnow()
        await db.flush()
        return app

    async def get(self, db: AsyncSession, application_id: str) -> ApplicationORM | None:
        result = await db.execute(
            select(ApplicationORM).where(ApplicationORM.id == application_id)
        )
        return result.scalar_one_or_none()


application_service = ApplicationService()
