"""LiquidityMonitor — continuous spread/depth/volume tracking and drought locks."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.domain.active_lock import ActiveLockCreate, ActiveLockType
from app.domain.instrument import InstrumentORM
from app.domain.market_data import MarketOhlcvORM, OrderBookSnapshotORM
from app.services.event_risk.repository import ActiveLockRepository
from app.services.liquidity.scoring import (
    compute_depth_ratio,
    compute_liquidity_score,
    total_depth_qty,
)
from app.services.liquidity.types import LiquidityAssessment, LiquidityTarget


class LiquidityMonitor:
    """Track per-instrument liquidity and enforce drought locks via active_locks."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        repository: ActiveLockRepository | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._repository = repository or ActiveLockRepository()

    async def locked_instrument_ids(
        self,
        db: AsyncSession,
        *,
        as_of: datetime | None = None,
    ) -> frozenset[int]:
        return await self._repository.locked_instrument_ids_by_type(
            db,
            lock_type=ActiveLockType.LIQUIDITY_DROUGHT,
            as_of=as_of,
        )

    async def assess_instrument(
        self,
        db: AsyncSession,
        instrument: InstrumentORM,
        *,
        as_of: datetime | None = None,
        drought_threshold: float | None = None,
    ) -> LiquidityAssessment | None:
        """Compute liquidity score for one instrument from stored market data."""
        now = self._utc(as_of)
        threshold = (
            drought_threshold
            if drought_threshold is not None
            else self._settings.LIQUIDITY_DROUGHT_THRESHOLD
        )
        depth_levels = self._settings.LIQUIDITY_DEPTH_LEVELS
        max_spread_bps = self._settings.LIQUIDITY_MAX_SPREAD_BPS

        snapshots = await self._load_order_book_history(
            db,
            instrument.id,
            limit=self._settings.LIQUIDITY_BASELINE_SNAPSHOTS + 1,
        )
        if not snapshots:
            return None

        latest = snapshots[0]
        baseline_snapshots = snapshots[1:] or snapshots[:1]
        baseline_bid, baseline_ask = self._average_depth(baseline_snapshots)

        spread_bps = float(latest.spread_bps) if latest.spread_bps is not None else None
        volume_ratio = await self._volume_ratio(db, instrument.id)

        depth_ratio = compute_depth_ratio(
            latest.bid_depth or [],
            latest.ask_depth or [],
            baseline_bid,
            baseline_ask,
            levels=depth_levels,
        )
        score = compute_liquidity_score(
            spread_bps=spread_bps,
            bid_depth=latest.bid_depth or [],
            ask_depth=latest.ask_depth or [],
            baseline_bid_depth=baseline_bid,
            baseline_ask_depth=baseline_ask,
            volume_ratio=volume_ratio,
            depth_levels=depth_levels,
            max_spread_bps=max_spread_bps,
        )
        drought = score < threshold
        reason = self._build_reason(
            symbol=instrument.symbol,
            score=score,
            threshold=threshold,
            spread_bps=spread_bps,
            depth_ratio=depth_ratio,
            volume_ratio=volume_ratio,
            drought=drought,
        )
        return LiquidityAssessment(
            target=LiquidityTarget(instrument_id=instrument.id, symbol=instrument.symbol),
            liquidity_score=score,
            spread_bps=spread_bps,
            depth_ratio=depth_ratio,
            volume_ratio=volume_ratio,
            drought=drought,
            reason=reason,
            assessed_at=now,
            metadata={
                "depth_levels": depth_levels,
                "baseline_depth_qty": total_depth_qty(baseline_bid, depth_levels)
                + total_depth_qty(baseline_ask, depth_levels),
                "current_depth_qty": total_depth_qty(latest.bid_depth or [], depth_levels)
                + total_depth_qty(latest.ask_depth or [], depth_levels),
            },
        )

    async def process_cycle(
        self,
        db: AsyncSession,
        *,
        as_of: datetime | None = None,
        drought_threshold: float | None = None,
    ) -> dict[str, int]:
        """Evaluate all instruments; create or release liquidity drought locks."""
        now = self._utc(as_of)
        await self._repository.expire_stale(db, as_of=now)

        instruments = await self._load_instruments(db)
        triggered = 0
        released = 0

        for instrument in instruments:
            assessment = await self.assess_instrument(
                db,
                instrument,
                as_of=now,
                drought_threshold=drought_threshold,
            )
            if assessment is None:
                continue

            has_lock = await self._repository.has_active_lock(
                db,
                instrument_id=instrument.id,
                as_of=now,
                lock_type=ActiveLockType.LIQUIDITY_DROUGHT,
            )
            if assessment.drought and not has_lock:
                await self._apply_drought_lock(db, assessment, as_of=now)
                triggered += 1
            elif not assessment.drought and has_lock:
                released += await self._repository.release_locks(
                    db,
                    instrument_id=instrument.id,
                    lock_type=ActiveLockType.LIQUIDITY_DROUGHT,
                )

        return {"triggered": triggered, "released": released, "assessed": len(instruments)}

    async def _apply_drought_lock(
        self,
        db: AsyncSession,
        assessment: LiquidityAssessment,
        *,
        as_of: datetime,
    ) -> None:
        expires_at = as_of + timedelta(minutes=self._settings.LIQUIDITY_DROUGHT_LOCK_TTL_MINUTES)
        severity = max(0.0, min(1.0, 1.0 - assessment.liquidity_score))
        await self._repository.create(
            db,
            ActiveLockCreate(
                lock_type=ActiveLockType.LIQUIDITY_DROUGHT,
                instrument_id=assessment.target.instrument_id,
                news_shock_score=severity,
                reason=assessment.reason,
                expires_at=expires_at,
                metadata={
                    "symbol": assessment.target.symbol,
                    "liquidity_score": assessment.liquidity_score,
                    "spread_bps": assessment.spread_bps,
                    "depth_ratio": assessment.depth_ratio,
                    "volume_ratio": assessment.volume_ratio,
                    **assessment.metadata,
                },
            ),
        )

    async def _load_instruments(self, db: AsyncSession) -> list[InstrumentORM]:
        result = await db.execute(select(InstrumentORM).order_by(InstrumentORM.symbol))
        return list(result.scalars().all())

    async def _load_order_book_history(
        self,
        db: AsyncSession,
        instrument_id: int,
        *,
        limit: int,
    ) -> list[OrderBookSnapshotORM]:
        result = await db.execute(
            select(OrderBookSnapshotORM)
            .where(OrderBookSnapshotORM.instrument_id == instrument_id)
            .order_by(desc(OrderBookSnapshotORM.time))
            .limit(limit)
        )
        return list(result.scalars().all())

    async def _volume_ratio(self, db: AsyncSession, instrument_id: int) -> float | None:
        lookback = self._settings.LIQUIDITY_VOLUME_LOOKBACK_BARS
        result = await db.execute(
            select(MarketOhlcvORM)
            .where(MarketOhlcvORM.instrument_id == instrument_id)
            .order_by(desc(MarketOhlcvORM.time))
            .limit(lookback + 1)
        )
        bars = list(result.scalars().all())
        if len(bars) < 2:
            return None

        latest_volume = bars[0].volume
        if latest_volume is None:
            return None
        historical = [bar.volume for bar in bars[1:] if bar.volume is not None]
        if not historical:
            return None

        avg_volume = sum(float(value) for value in historical) / len(historical)
        if avg_volume <= 0:
            return None
        return float(latest_volume) / avg_volume

    @staticmethod
    def _average_depth(
        snapshots: list[OrderBookSnapshotORM],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        if not snapshots:
            return [], []

        bid_totals: dict[str, float] = {}
        ask_totals: dict[str, float] = {}
        count = len(snapshots)

        for snapshot in snapshots:
            for level in snapshot.bid_depth or []:
                price = str(level.get("price", ""))
                try:
                    qty = float(level.get("qty", 0))
                except (TypeError, ValueError):
                    qty = 0.0
                bid_totals[price] = bid_totals.get(price, 0.0) + qty
            for level in snapshot.ask_depth or []:
                price = str(level.get("price", ""))
                try:
                    qty = float(level.get("qty", 0))
                except (TypeError, ValueError):
                    qty = 0.0
                ask_totals[price] = ask_totals.get(price, 0.0) + qty

        bid_depth = [
            {"price": price, "qty": str(qty / count)}
            for price, qty in sorted(bid_totals.items(), key=lambda item: float(item[0]), reverse=True)
        ]
        ask_depth = [
            {"price": price, "qty": str(qty / count)}
            for price, qty in sorted(ask_totals.items(), key=lambda item: float(item[0]))
        ]
        return bid_depth, ask_depth

    @staticmethod
    def _build_reason(
        *,
        symbol: str,
        score: float,
        threshold: float,
        spread_bps: float | None,
        depth_ratio: float,
        volume_ratio: float | None,
        drought: bool,
    ) -> str:
        spread_text = f"{spread_bps:.1f} bps" if spread_bps is not None else "n/a"
        volume_text = f"{volume_ratio:.2f}x avg" if volume_ratio is not None else "n/a"
        state = "liquidity_drought" if drought else "liquidity_ok"
        return (
            f"{state} for {symbol}: score {score:.3f} "
            f"(threshold {threshold:.3f}), spread {spread_text}, "
            f"depth ratio {depth_ratio:.3f}, volume {volume_text}"
        )

    @staticmethod
    def _utc(value: datetime | None) -> datetime:
        if value is None:
            return datetime.now(timezone.utc)
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


def resolve_liquidity_threshold(profile_diversification: dict[str, Any] | None, settings: Settings) -> float:
    """Read min liquidity score threshold from profile policy with settings fallback."""
    policy = profile_diversification or {}
    raw = policy.get("min_liquidity_score", settings.LIQUIDITY_DROUGHT_THRESHOLD)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = settings.LIQUIDITY_DROUGHT_THRESHOLD
    return min(1.0, max(0.0, value))


_monitor = LiquidityMonitor()


def get_liquidity_monitor() -> LiquidityMonitor:
    return _monitor
