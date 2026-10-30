"""Load live portfolio snapshots for StressHarness (Prompt 27)."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Maneuver, ManeuverStatus
from app.domain.deal_intent import DealIntentORM
from app.domain.deal_intent_enums import DealIntentStatus
from app.domain.instrument import InstrumentORM
from app.domain.market_data import FactorExposureORM, MarketOhlcvORM, SectorMappingORM
from app.domain.sleeve import SleeveORM, SleeveRead
from app.services.factor.types import FactorName
from app.services.market_graph.builder import returns_from_closes
from app.services.scenario.types import PortfolioPosition, PortfolioSnapshot

_ACTIVE_INTENT_STATUSES = frozenset(
    status.value
    for status in (
        DealIntentStatus.EXECUTING,
        DealIntentStatus.FILLED,
    )
)

_ACTIVE_MANEUVER_STATUSES = (
    ManeuverStatus.EXECUTING.value,
    ManeuverStatus.FILLED.value,
)


@dataclass(frozen=True, slots=True)
class ProfilePortfolioContext:
    """Portfolio snapshot plus sleeve budgets for stress testing."""

    profile_id: str
    portfolio: PortfolioSnapshot
    sleeve_risk_budgets: dict[str, Decimal]
    portfolio_value_usd: float
    sleeves: tuple[SleeveRead, ...]


@dataclass(frozen=True, slots=True)
class StressHarnessLoaderConfig:
    timeframe: str = "1d"
    lookback_bars: int = 60
    default_portfolio_value_usd: float = 100_000.0


class StressHarnessLoader:
    """Build PortfolioSnapshot from profile sleeves and open exposure."""

    def __init__(self, *, config: StressHarnessLoaderConfig | None = None) -> None:
        self._config = config or StressHarnessLoaderConfig()

    async def load_profile_portfolio(
        self,
        db: AsyncSession,
        profile_id: str,
        *,
        portfolio_value_usd: float | None = None,
    ) -> ProfilePortfolioContext:
        sleeves = await self._load_sleeves(db, profile_id)
        sleeve_budgets = {sleeve.id: sleeve.risk_budget for sleeve in sleeves}
        default_sleeve_id = sleeves[0].id if sleeves else "default"

        positions = await self._load_deal_intent_positions(db, profile_id)
        if not positions:
            positions = await self._load_maneuver_positions(db, default_sleeve_id)

        normalized = _normalize_positions(positions)
        instrument_ids = sorted({position.instrument_id for position in normalized})

        factor_exposures = await self._load_factor_exposures(db, instrument_ids)
        returns_by_instrument = await self._load_returns(db, instrument_ids)
        sector_by_instrument = await self._load_sectors(db, instrument_ids)

        total_value = portfolio_value_usd
        if total_value is None:
            total_value = float(
                sum(float(position.weight) for position in normalized)
                * self._config.default_portfolio_value_usd
            )
            if total_value <= 0.0:
                total_value = self._config.default_portfolio_value_usd

        portfolio = PortfolioSnapshot(
            positions=tuple(normalized),
            factor_exposures=factor_exposures,
            returns_by_instrument=returns_by_instrument,
            sector_by_instrument=sector_by_instrument or None,
        )
        return ProfilePortfolioContext(
            profile_id=profile_id,
            portfolio=portfolio,
            sleeve_risk_budgets=sleeve_budgets,
            portfolio_value_usd=total_value,
            sleeves=tuple(sleeves),
        )

    async def _load_sleeves(self, db: AsyncSession, profile_id: str) -> list[SleeveRead]:
        result = await db.execute(
            select(SleeveORM)
            .where(SleeveORM.profile_id == profile_id)
            .order_by(SleeveORM.created_at)
        )
        return [SleeveRead.model_validate(row) for row in result.scalars().all()]

    async def _load_deal_intent_positions(
        self,
        db: AsyncSession,
        profile_id: str,
    ) -> list[PortfolioPosition]:
        result = await db.execute(
            select(DealIntentORM, SleeveORM.id)
            .join(SleeveORM, DealIntentORM.sleeve_id == SleeveORM.id)
            .where(
                SleeveORM.profile_id == profile_id,
                DealIntentORM.status.in_(_ACTIVE_INTENT_STATUSES),
            )
        )
        raw_weights: dict[tuple[int, str], float] = {}
        for intent, sleeve_id in result.all():
            exit_logic = intent.exit_logic or {}
            weight = _intent_weight(intent, exit_logic)
            key = (intent.instrument_id, sleeve_id)
            raw_weights[key] = raw_weights.get(key, 0.0) + weight

        return [
            PortfolioPosition(
                instrument_id=instrument_id,
                sleeve_id=sleeve_id,
                weight=weight,
            )
            for (instrument_id, sleeve_id), weight in raw_weights.items()
        ]

    async def _load_maneuver_positions(
        self,
        db: AsyncSession,
        default_sleeve_id: str,
    ) -> list[PortfolioPosition]:
        result = await db.execute(
            select(Maneuver).where(Maneuver.status.in_(_ACTIVE_MANEUVER_STATUSES))
        )
        maneuvers = result.scalars().all()
        if not maneuvers:
            return []

        tickers = sorted({maneuver.ticker.upper() for maneuver in maneuvers})
        instrument_map = await self._instruments_by_symbol(db, tickers)

        raw_weights: dict[tuple[int, str], float] = {}
        for maneuver in maneuvers:
            instrument_id = instrument_map.get(maneuver.ticker.upper())
            if instrument_id is None:
                continue
            size = float(maneuver.position_size_usd or 0.0)
            if size <= 0.0:
                size = float(maneuver.risk_percent or 0.0)
            key = (instrument_id, default_sleeve_id)
            raw_weights[key] = raw_weights.get(key, 0.0) + size

        return [
            PortfolioPosition(
                instrument_id=instrument_id,
                sleeve_id=sleeve_id,
                weight=weight,
            )
            for (instrument_id, sleeve_id), weight in raw_weights.items()
        ]

    async def _instruments_by_symbol(
        self,
        db: AsyncSession,
        symbols: list[str],
    ) -> dict[str, int]:
        if not symbols:
            return {}
        result = await db.execute(
            select(InstrumentORM.id, InstrumentORM.symbol).where(
                func.upper(InstrumentORM.symbol).in_(symbols)
            )
        )
        return {symbol.upper(): instrument_id for instrument_id, symbol in result.all()}

    async def _load_factor_exposures(
        self,
        db: AsyncSession,
        instrument_ids: list[int],
    ) -> dict[int, dict[FactorName, float]]:
        if not instrument_ids:
            return {}

        latest_time_subq = (
            select(
                FactorExposureORM.instrument_id,
                func.max(FactorExposureORM.time).label("max_time"),
            )
            .where(FactorExposureORM.instrument_id.in_(instrument_ids))
            .group_by(FactorExposureORM.instrument_id)
            .subquery()
        )
        stmt = select(FactorExposureORM).join(
            latest_time_subq,
            (FactorExposureORM.instrument_id == latest_time_subq.c.instrument_id)
            & (FactorExposureORM.time == latest_time_subq.c.max_time),
        )
        rows = (await db.execute(stmt)).scalars().all()

        exposures: dict[int, dict[FactorName, float]] = {}
        for row in rows:
            factor = FactorName(row.factor_name)
            exposures.setdefault(row.instrument_id, {})[factor] = float(row.beta)
        return exposures

    async def _load_returns(
        self,
        db: AsyncSession,
        instrument_ids: list[int],
    ) -> dict[int, list[float]]:
        if not instrument_ids:
            return {}

        returns_by_instrument: dict[int, list[float]] = {}
        for instrument_id in instrument_ids:
            result = await db.execute(
                select(MarketOhlcvORM.close)
                .where(
                    MarketOhlcvORM.instrument_id == instrument_id,
                    MarketOhlcvORM.timeframe == self._config.timeframe,
                    MarketOhlcvORM.close.is_not(None),
                )
                .order_by(desc(MarketOhlcvORM.time))
                .limit(self._config.lookback_bars + 1)
            )
            closes = [float(value) for value in result.scalars().all()]
            closes.reverse()
            series = returns_from_closes(closes)
            if series:
                returns_by_instrument[instrument_id] = series
        return returns_by_instrument

    async def _load_sectors(
        self,
        db: AsyncSession,
        instrument_ids: list[int],
    ) -> dict[int, str]:
        if not instrument_ids:
            return {}
        result = await db.execute(
            select(SectorMappingORM).where(
                SectorMappingORM.instrument_id.in_(instrument_ids)
            )
        )
        return {row.instrument_id: row.sector for row in result.scalars().all()}


def _intent_weight(intent: DealIntentORM, exit_logic: dict) -> float:
    for key in ("position_weight", "weight", "market_value_usd", "notional_usd"):
        value = exit_logic.get(key)
        if value is not None:
            parsed = float(value)
            if parsed > 0.0:
                return parsed
    threshold = float(intent.approval_threshold or 0.0)
    if threshold > 0.0:
        return threshold
    return 1.0


def _normalize_positions(positions: list[PortfolioPosition]) -> list[PortfolioPosition]:
    if not positions:
        return []
    total = sum(position.weight for position in positions)
    if total <= 0.0:
        equal = 1.0 / len(positions)
        return [
            PortfolioPosition(
                instrument_id=position.instrument_id,
                sleeve_id=position.sleeve_id,
                weight=equal,
            )
            for position in positions
        ]
    return [
        PortfolioPosition(
            instrument_id=position.instrument_id,
            sleeve_id=position.sleeve_id,
            weight=position.weight / total,
        )
        for position in positions
    ]
