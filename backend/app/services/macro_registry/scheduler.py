"""Macro refresh scheduler (Prompt 47)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domain.macro_registry import MacroCalendarEntryORM, MacroSourceRegistryORM

logger = get_logger(__name__)


class MacroRefreshScheduler:
    """Manage daily, weekly, and event-driven macro refreshes."""

    def __init__(self) -> None:
        self._last_refresh: dict[str, datetime] = {}
        self._queue_lag_seconds: dict[str, float] = {}

    def is_due(self, source: MacroSourceRegistryORM, now: datetime | None = None) -> bool:
        ts = now or datetime.now(timezone.utc)
        interval_hours = _refresh_interval_hours(source.refresh_interval)
        last = source.last_successful_refresh
        if last is None:
            return True
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        elapsed = (ts - last).total_seconds() / 3600.0
        return elapsed >= interval_hours

    async def sources_due_for_refresh(
        self,
        session: AsyncSession,
        *,
        now: datetime | None = None,
    ) -> list[MacroSourceRegistryORM]:
        stmt = select(MacroSourceRegistryORM).where(MacroSourceRegistryORM.is_active.is_(True))
        sources = list((await session.execute(stmt)).scalars().all())
        return [s for s in sources if self.is_due(s, now)]

    async def run_daily_refresh(
        self,
        session: AsyncSession,
        service: Any,
    ) -> dict[str, Any]:
        due = await self.sources_due_for_refresh(session)
        results: dict[str, Any] = {"refreshed": [], "skipped": [], "errors": {}}
        for source in due:
            if source.category == "calendar":
                try:
                    await service.refresh_calendar(session, source.source_id)
                    results["refreshed"].append(source.source_id)
                except Exception as exc:
                    results["errors"][source.source_id] = str(exc)
                continue
            try:
                await service.refresh_source(session, source.source_id)
                results["refreshed"].append(source.source_id)
            except Exception as exc:
                logger.warning("macro_refresh_failed", source_id=source.source_id, error=str(exc))
                if source.fallback_source:
                    try:
                        await service.refresh_source(session, source.fallback_source)
                        results["refreshed"].append(source.fallback_source)
                    except Exception as fb_exc:
                        results["errors"][source.source_id] = str(fb_exc)
                else:
                    results["errors"][source.source_id] = str(exc)
        return results

    async def run_event_driven_refresh(
        self,
        session: AsyncSession,
        service: Any,
        *,
        now: datetime | None = None,
        lookback_minutes: int = 90,
    ) -> dict[str, Any]:
        """Force-refresh sources whose calendar release window just elapsed."""
        ts = now or datetime.now(timezone.utc)
        window_start = ts - timedelta(minutes=lookback_minutes)
        stmt = (
            select(MacroCalendarEntryORM)
            .where(
                MacroCalendarEntryORM.expected_release_time >= window_start,
                MacroCalendarEntryORM.expected_release_time <= ts,
            )
            .order_by(MacroCalendarEntryORM.expected_release_time.desc())
        )
        entries = list((await session.execute(stmt)).scalars().all())
        source_ids = sorted({entry.source_id for entry in entries})
        results: dict[str, Any] = {"refreshed": [], "skipped": [], "errors": {}}
        for source_id in source_ids:
            row = await service.get_source(session, source_id)
            if row is None or not row.is_active:
                results["skipped"].append(source_id)
                continue
            try:
                if row.category == "calendar":
                    await service.refresh_calendar(session, source_id)
                else:
                    await service.refresh_source(session, source_id)
                self.record_refresh(source_id, ts)
                results["refreshed"].append(source_id)
            except Exception as exc:
                logger.warning(
                    "macro_event_refresh_failed",
                    source_id=source_id,
                    error=str(exc),
                )
                results["errors"][source_id] = str(exc)
        return results

    async def run_weekly_deep_report(
        self,
        session: AsyncSession,
        report_engine: Any,
        storage: Any,
    ) -> dict[str, Any]:
        report = await report_engine.generate(session, mode="weekly")
        snap = await storage.build_report_snapshot(
            session,
            snapshot_type="weekly",
            payload=report,
            markdown=report.get("markdown"),
        )
        await session.commit()
        return {"snapshot_id": snap.id, "mode": "weekly"}

    def record_refresh(self, source_id: str, ts: datetime | None = None) -> None:
        now = ts or datetime.now(timezone.utc)
        previous = self._last_refresh.get(source_id)
        if previous is not None:
            if previous.tzinfo is None:
                previous = previous.replace(tzinfo=timezone.utc)
            self._queue_lag_seconds[source_id] = max(0.0, (now - previous).total_seconds())
        self._last_refresh[source_id] = now

    def get_refresh_status(self) -> dict[str, str]:
        return {k: v.isoformat() for k, v in self._last_refresh.items()}

    def get_queue_lag_seconds(self) -> dict[str, float]:
        return dict(self._queue_lag_seconds)


def _refresh_interval_hours(cron_expr: str) -> float:
    """Approximate cron refresh_interval to hours (no extra deps)."""
    if "*/30" in cron_expr:
        return 0.5
    if "* * 1-5" in cron_expr:
        return 24.0
    if "15 * *" in cron_expr:
        return 720.0
    if "1 * *" in cron_expr:
        return 720.0
    return 24.0
