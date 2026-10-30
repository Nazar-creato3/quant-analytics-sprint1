"""Record which legal texts a person accepted (152-ФЗ, ст. 9: оператор доказывает согласие).

Each tick is stored with the document code, its version and sha256 at that
moment, the time, IP and browser, so the exact text the person saw can be
shown later.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LegalAcceptance
from app.services.legal.catalog import CatalogError, get_document

REGISTRATION_DOCUMENTS = ("terms", "privacy", "consent_pd")
# Consents given later, at the moment a feature needs them; each is separate.
OPTIONAL_DOCUMENTS = ("consent_broker", "consent_marketing")
REVOCABLE_DOCUMENTS = REGISTRATION_DOCUMENTS + OPTIONAL_DOCUMENTS


def _doc_ref(code: str) -> tuple[str, str | None]:
    try:
        row = get_document(code)
    except CatalogError:
        row = None
    if not row:
        return "unknown", None
    return str(row.get("version") or "unknown"), row.get("sha256")


async def record_acceptance(
    db: AsyncSession, user_id: str, code: str, *, ip: str | None, user_agent: str | None
) -> LegalAcceptance:
    version, sha = _doc_ref(code)
    row = LegalAcceptance(
        user_id=user_id,
        document_code=code,
        document_version=version,
        document_sha256=sha,
        accepted_at=datetime.now(timezone.utc),
        ip=(ip or None),
        user_agent=(user_agent or "")[:400] or None,
    )
    db.add(row)
    return row


async def record_registration_consents(
    db: AsyncSession, user_id: str, *, ip: str | None, user_agent: str | None
) -> list[LegalAcceptance]:
    rows = [await record_acceptance(db, user_id, code, ip=ip, user_agent=user_agent) for code in REGISTRATION_DOCUMENTS]
    await db.flush()
    return rows


async def list_acceptances(db: AsyncSession, user_id: str) -> list[dict[str, Any]]:
    res = await db.execute(
        select(LegalAcceptance).where(LegalAcceptance.user_id == user_id).order_by(LegalAcceptance.accepted_at)
    )
    return [
        {
            "document": r.document_code,
            "version": r.document_version,
            "sha256": r.document_sha256,
            "accepted_at": r.accepted_at.isoformat() if r.accepted_at else None,
            "revoked_at": r.revoked_at.isoformat() if r.revoked_at else None,
        }
        for r in res.scalars().all()
    ]


async def has_active(db: AsyncSession, user_id: str, code: str) -> bool:
    res = await db.execute(
        select(LegalAcceptance.id)
        .where(
            LegalAcceptance.user_id == user_id,
            LegalAcceptance.document_code == code,
            LegalAcceptance.revoked_at.is_(None),
        )
        .limit(1)
    )
    return res.first() is not None


async def revoke(db: AsyncSession, user_id: str, code: str) -> int:
    res = await db.execute(
        update(LegalAcceptance)
        .where(LegalAcceptance.user_id == user_id, LegalAcceptance.document_code == code, LegalAcceptance.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )
    return int(res.rowcount or 0)
