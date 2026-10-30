"""FactorEngine — rolling multi-factor return decomposition (Prompt 19)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.market_data import MacroIndicatorORM, MarketOhlcvORM, SectorMappingORM
from app.services.factor.factor_returns import (
    InstrumentReturnPoint,
    build_factor_return_matrix,
    group_returns_by_sector,
    macro_points_from_rows,
)
from app.services.factor.regression import rolling_factor_regression
from app.services.factor.repository import FactorExposureRepository
from app.services.factor.types import ALL_FACTORS, FactorExposureRow, FactorName
from app.services.quant_math import log_return


def _bar_day(ts: datetime) -> datetime:
    """Normalize bar timestamps to UTC calendar days for cross-asset alignment."""
    if ts.tzinfo is None:
        aware = ts.replace(tzinfo=timezone.utc)
    else:
        aware = ts.astimezone(timezone.utc)
    return datetime(aware.year, aware.month, aware.day, tzinfo=timezone.utc)


@dataclass(frozen=True, slots=True)
class FactorEngineConfig:
    """Runtime parameters for rolling factor estimation."""

    window: int = 60
    timeframe: str = "1d"
    momentum_lookback: int = 5
    min_macro_points: int = 2


class FactorEngine:
    """Decompose instrument returns into macro/sector/style factor exposures."""

    def __init__(
        self,
        *,
        config: FactorEngineConfig | None = None,
        repository: FactorExposureRepository | None = None,
    ) -> None:
        self._config = config or FactorEngineConfig()
        self._repository = repository or FactorExposureRepository()

    def estimate_from_series(
        self,
        *,
        instrument_id: int,
        timestamps: Sequence[datetime],
        instrument_returns: Sequence[float],
        factor_returns: Mapping[FactorName, Sequence[float]],
    ) -> list[FactorExposureRow]:
        """Pure estimation path for tests and offline replay."""
        rolling = rolling_factor_regression(
            instrument_returns,
            factor_returns,
            window=self._config.window,
        )
        rows: list[FactorExposureRow] = []
        for result in rolling:
            timestamp = timestamps[result.time_index]
            for factor_name in ALL_FACTORS:
                beta = result.betas.get(factor_name, 0.0)
                rows.append(
                    FactorExposureRow(
                        instrument_id=instrument_id,
                        time=timestamp,
                        factor_name=factor_name,
                        beta=beta,
                        r_squared_of_model=result.r_squared,
                    )
                )
        return rows

    async def estimate_for_instrument(
        self,
        session: AsyncSession,
        *,
        instrument_id: int,
        lookback_bars: int | None = None,
        as_of: datetime | None = None,
    ) -> list[FactorExposureRow]:
        """Load market/macro data and compute rolling factor exposures."""
        bars_limit = lookback_bars or max(self._config.window * 3, 120)
        returns_bundle = await self._load_return_universe(session, bars_limit=bars_limit, as_of=as_of)
        if instrument_id not in returns_bundle.returns_by_instrument:
            return []

        timestamps = returns_bundle.timestamps
        sector = returns_bundle.sector_by_instrument.get(instrument_id)
        sector_peers = (
            returns_bundle.sector_groups.get(sector, {})
            if sector is not None
            else {}
        )
        instrument_series = returns_bundle.returns_by_instrument[instrument_id]
        instrument_returns = [value for _, value in instrument_series]
        # as_of backfill can yield empty aligned series when calendars diverge;
        # treat as "no exposures" instead of raising in rolling regression.
        if not timestamps or not instrument_returns:
            return []

        factor_matrix = build_factor_return_matrix(
            timestamps=timestamps,
            instrument_returns=returns_bundle.returns_by_instrument,
            sector_peers=sector_peers,
            macro_by_code=returns_bundle.macro_by_code,
            exclude_instrument_id=instrument_id,
            momentum_lookback=self._config.momentum_lookback,
        )
        return self.estimate_from_series(
            instrument_id=instrument_id,
            timestamps=timestamps,
            instrument_returns=instrument_returns,
            factor_returns=factor_matrix,
        )

    async def estimate_and_persist(
        self,
        session: AsyncSession,
        *,
        instrument_id: int,
        lookback_bars: int | None = None,
        as_of: datetime | None = None,
    ) -> int:
        rows = await self.estimate_for_instrument(
            session,
            instrument_id=instrument_id,
            lookback_bars=lookback_bars,
            as_of=as_of,
        )
        return await self._repository.upsert_exposures(session, rows)

    async def _load_return_universe(
        self,
        session: AsyncSession,
        *,
        bars_limit: int,
        as_of: datetime | None,
    ) -> "_ReturnUniverse":
        sector_rows = await session.execute(select(SectorMappingORM))
        sector_by_instrument = {
            row.instrument_id: row.sector for row in sector_rows.scalars().all()
        }
        instrument_ids = list(sector_by_instrument.keys())
        if not instrument_ids:
            return _ReturnUniverse([], {}, {}, {}, sector_by_instrument)

        ohlcv_stmt = (
            select(MarketOhlcvORM)
            .where(
                MarketOhlcvORM.instrument_id.in_(instrument_ids),
                MarketOhlcvORM.timeframe == self._config.timeframe,
            )
            .order_by(MarketOhlcvORM.instrument_id, MarketOhlcvORM.time)
        )
        if as_of is not None:
            ohlcv_stmt = ohlcv_stmt.where(MarketOhlcvORM.time <= as_of)
        ohlcv_rows = (await session.execute(ohlcv_stmt)).scalars().all()

        closes_by_instrument: dict[int, list[tuple[datetime, float]]] = {}
        for row in ohlcv_rows:
            if row.close is None:
                continue
            closes_by_instrument.setdefault(row.instrument_id, []).append(
                (row.time, float(row.close))
            )

        timestamps = _shared_timestamps(closes_by_instrument, limit=bars_limit)
        returns_by_instrument: dict[int, list[InstrumentReturnPoint]] = {}
        for instrument_id, closes in closes_by_instrument.items():
            aligned = _align_closes(timestamps, closes)
            if not aligned:
                continue
            returns_by_instrument[instrument_id] = _returns_from_closes(timestamps, aligned)

        sector_groups = group_returns_by_sector(
            instrument_ids,
            sector_by_instrument,
            returns_by_instrument,
        )
        macro_rows = await session.execute(
            select(MacroIndicatorORM).order_by(MacroIndicatorORM.published_at)
        )
        macro_by_code = macro_points_from_rows(
            [
                {
                    "indicator_code": row.indicator_code,
                    "published_at": row.published_at,
                    "value": row.value,
                }
                for row in macro_rows.scalars().all()
            ]
        )
        return _ReturnUniverse(
            timestamps,
            returns_by_instrument,
            sector_groups,
            macro_by_code,
            sector_by_instrument,
        )


@dataclass(frozen=True, slots=True)
class _ReturnUniverse:
    timestamps: list[datetime]
    returns_by_instrument: dict[int, list[InstrumentReturnPoint]]
    sector_groups: dict[str, dict[int, list[InstrumentReturnPoint]]]
    macro_by_code: dict[str, list[tuple[datetime, float]]]
    sector_by_instrument: dict[int, str]


def _shared_timestamps(
    closes_by_instrument: Mapping[int, list[tuple[datetime, float]]],
    *,
    limit: int,
) -> list[datetime]:
    if not closes_by_instrument:
        return []
    # Align on calendar day so equity (session close) and crypto (00:00 UTC)
    # bars still intersect — exact datetime equality emptied as_of backfills.
    common: set[datetime] | None = None
    for closes in closes_by_instrument.values():
        if not closes:
            continue
        times = {_bar_day(timestamp) for timestamp, _ in closes}
        common = times if common is None else common & times
    if not common:
        # Fall back to the densest single instrument calendar rather than empty.
        densest = max(closes_by_instrument.values(), key=len, default=[])
        common = {_bar_day(timestamp) for timestamp, _ in densest}
    if not common:
        return []
    ordered = sorted(common)
    if len(ordered) > limit:
        ordered = ordered[-limit:]
    return ordered


def _align_closes(timestamps: Sequence[datetime], closes: Sequence[tuple[datetime, float]]) -> list[float]:
    lookup: dict[datetime, float] = {}
    for timestamp, price in closes:
        lookup[_bar_day(timestamp)] = price
    aligned: list[float] = []
    for timestamp in timestamps:
        price = lookup.get(timestamp)
        if price is None:
            return []
        aligned.append(price)
    return aligned


def _returns_from_closes(
    timestamps: Sequence[datetime],
    closes: Sequence[float],
) -> list[InstrumentReturnPoint]:
    if not closes:
        return []
    returns: list[InstrumentReturnPoint] = [(timestamps[0], 0.0)]
    for index in range(1, len(closes)):
        prev = closes[index - 1]
        curr = closes[index]
        if prev <= 0.0 or curr <= 0.0:
            value = 0.0
        else:
            value = log_return(curr, prev)
        returns.append((timestamps[index], value))
    return returns
