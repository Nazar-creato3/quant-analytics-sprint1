"""Fuzzy duplicate detection for applications."""
from __future__ import annotations

from difflib import SequenceMatcher

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.application_flow import ApplicationORM, ApplicationStatus


def _normalize_phone(phone: str) -> str:
    return "".join(c for c in phone if c.isdigit())


def _similarity(a: str | None, b: str | None) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


async def detect_duplicate_application(
    db: AsyncSession,
    *,
    email: str,
    name: str | None,
    phone: str,
    phone_hash: str,
    exclude_id: str | None = None,
) -> tuple[bool, str | None]:
    """Return (is_duplicate, reason) using email exact match, phone hash, or fuzzy name+phone."""
    normalized_email = email.strip().lower()
    normalized_phone = _normalize_phone(phone)

    q = select(ApplicationORM).where(
        ApplicationORM.status.notin_(
            [ApplicationStatus.REJECTED.value]
        )
    )
    if exclude_id:
        q = q.where(ApplicationORM.id != exclude_id)

    result = await db.execute(q)
    candidates = list(result.scalars().all())

    for row in candidates:
        if row.email == normalized_email:
            return True, "duplicate_email"
        if row.phone_hash == phone_hash:
            return True, "duplicate_phone_hash"
        row_phone = _normalize_phone(row.phone)
        if row_phone == normalized_phone:
            return True, "duplicate_phone"
        name_sim = _similarity(name, row.name)
        if name_sim >= 0.85 and row_phone == normalized_phone:
            return True, f"fuzzy_name_phone:{name_sim:.2f}"

    # Trigram-style fuzzy name + similar phone prefix
    for row in candidates:
        if _similarity(name, row.name) >= 0.9:
            row_phone = _normalize_phone(row.phone)
            if row_phone[-7:] == normalized_phone[-7:] and len(normalized_phone) >= 7:
                return True, "fuzzy_name_phone_suffix"

    return False, None
