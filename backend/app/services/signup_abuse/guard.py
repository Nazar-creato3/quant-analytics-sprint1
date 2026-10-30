"""SignupAbuseGuard — risk signals for AccessPolicy (Prompt 65)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.admissions import AdmissionCaseORM
from app.domain.device_identity import ClusterMemberType, IdentityClusterMemberORM
from app.utils.cache import rate_limit_check

# Minimal disposable-domain set (extend via job later).
DISPOSABLE_DOMAINS = frozenset(
    {
        "mailinator.com",
        "guerrillamail.com",
        "tempmail.com",
        "10minutemail.com",
        "yopmail.com",
        "trashmail.com",
        "sharklasers.com",
    }
)

_EMAIL_RE = re.compile(r"^[^@\s]+@([^@\s]+)$")


@dataclass
class AbuseSignals:
    disposable_email: bool = False
    velocity_flag: bool = False
    proxy_risk: float = 0.0
    timezone_mismatch: bool = False
    phone_duplicate: bool = False
    payment_duplicate: bool = False
    details: list[str] = field(default_factory=list)


@dataclass
class AbuseScoreResult:
    risk_score: float
    signals: AbuseSignals
    decision_hint: str  # allow | manual_review | block — hint only; AccessPolicy decides


def is_disposable_email(email: str) -> bool:
    m = _EMAIL_RE.match(email.strip().lower())
    if not m:
        return False
    domain = m.group(1)
    return domain in DISPOSABLE_DOMAINS


async def velocity_check_redis(ip_range: str, *, window_minutes: int = 60, max_count: int = 15) -> bool:
    """Redis-backed signup velocity check. True when threshold exceeded."""
    if not ip_range:
        return False
    allowed, _remaining = await rate_limit_check(
        f"signup_velocity:{ip_range}",
        max_count,
        window_minutes * 60,
        fail_closed=True,
    )
    return not allowed


async def phone_exists_in_db(db: AsyncSession, phone: str | None) -> bool:
    if not phone or len(phone.strip()) < 5:
        return False
    normalized = phone.strip()
    result = await db.execute(
        select(func.count())
        .select_from(AdmissionCaseORM)
        .where(AdmissionCaseORM.contact_phone == normalized)
    )
    return int(result.scalar_one() or 0) > 0


async def payment_instrument_exists_in_db(db: AsyncSession, payment_hash: str | None) -> bool:
    if not payment_hash:
        return False
    result = await db.execute(
        select(func.count())
        .select_from(IdentityClusterMemberORM)
        .where(
            IdentityClusterMemberORM.member_type == ClusterMemberType.PAYMENT_HASH.value,
            IdentityClusterMemberORM.member_key == payment_hash,
        )
    )
    return int(result.scalar_one() or 0) > 0


async def score_signup_abuse_async(
    db: AsyncSession,
    *,
    email: str,
    ip_range: str | None = None,
    proxy_risk: float = 0.0,
    timezone_mismatch: bool = False,
    phone: str | None = None,
    payment_instrument_hash: str | None = None,
) -> AbuseScoreResult:
    phone_duplicate = await phone_exists_in_db(db, phone)
    payment_duplicate = await payment_instrument_exists_in_db(db, payment_instrument_hash)
    return score_signup_abuse(
        email=email,
        ip_range=ip_range,
        proxy_risk=proxy_risk,
        timezone_mismatch=timezone_mismatch,
        phone_duplicate=phone_duplicate,
        payment_duplicate=payment_duplicate,
        velocity_flag=await velocity_check_redis(ip_range or ""),
    )


def score_signup_abuse(
    *,
    email: str,
    ip_range: str | None = None,
    proxy_risk: float = 0.0,
    timezone_mismatch: bool = False,
    phone_duplicate: bool = False,
    payment_duplicate: bool = False,
    velocity_flag: bool = False,
) -> AbuseScoreResult:
    signals = AbuseSignals(
        disposable_email=is_disposable_email(email),
        proxy_risk=max(0.0, min(1.0, proxy_risk)),
        timezone_mismatch=timezone_mismatch,
        phone_duplicate=phone_duplicate,
        payment_duplicate=payment_duplicate,
        velocity_flag=velocity_flag,
    )
    score = 0.0
    if signals.disposable_email:
        score += 0.35
        signals.details.append("disposable_email")
    if signals.velocity_flag:
        score += 0.3
        signals.details.append("velocity")
    if signals.proxy_risk >= 0.5:
        score += 0.2 * signals.proxy_risk
        signals.details.append("proxy_risk")
    if signals.timezone_mismatch:
        score += 0.15
        signals.details.append("timezone_mismatch")
    if signals.phone_duplicate:
        score += 0.25
        signals.details.append("phone_duplicate")
    if signals.payment_duplicate:
        score += 0.35
        signals.details.append("payment_duplicate")

    score = min(1.0, score)
    if score >= 0.85:
        hint = "block"
    elif score >= 0.45:
        hint = "manual_review"
    else:
        hint = "allow"
    return AbuseScoreResult(risk_score=score, signals=signals, decision_hint=hint)
