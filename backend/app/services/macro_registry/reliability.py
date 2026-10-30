"""Per-source rolling reliability score (Prompt 48 amendment)."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.macro_registry import MacroSourceRegistryORM

DEFAULT_RELIABILITY = 1.0
DECAY_ALPHA = 0.15  # exponential decay weight for new observation
PASS_WEIGHT = 1.0
FAIL_WEIGHT = 0.0


def update_reliability_score(current: float, *, passed: bool) -> float:
    """Exponential decay update toward pass (1.0) or fail (0.0)."""
    target = PASS_WEIGHT if passed else FAIL_WEIGHT
    updated = (1.0 - DECAY_ALPHA) * current + DECAY_ALPHA * target
    return round(max(0.0, min(1.0, updated)), 4)


def adjust_confidence_for_reliability(confidence: float, reliability_score: float) -> float:
    """Lower observation confidence when source reliability is degraded."""
    adjusted = confidence * max(0.35, reliability_score)
    return round(max(0.0, min(1.0, adjusted)), 4)


async def apply_reliability_update(
    session: AsyncSession,
    source_id: str,
    *,
    passed: bool,
) -> float:
    """Update macro_source_registry.reliability_score after quality-gate evaluation."""
    row = (
        await session.execute(
            select(MacroSourceRegistryORM).where(MacroSourceRegistryORM.source_id == source_id)
        )
    ).scalar_one_or_none()
    if row is None:
        return DEFAULT_RELIABILITY
    current = float(getattr(row, "reliability_score", DEFAULT_RELIABILITY) or DEFAULT_RELIABILITY)
    updated = update_reliability_score(current, passed=passed)
    row.reliability_score = updated
    row.updated_at = datetime.now(timezone.utc)
    await session.flush()
    return updated


async def get_reliability_scores(session: AsyncSession) -> dict[str, float]:
    rows = list((await session.execute(select(MacroSourceRegistryORM))).scalars().all())
    return {
        row.source_id: float(getattr(row, "reliability_score", DEFAULT_RELIABILITY) or DEFAULT_RELIABILITY)
        for row in rows
    }
