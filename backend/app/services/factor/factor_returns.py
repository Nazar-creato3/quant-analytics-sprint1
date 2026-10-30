"""Factor return series built from macro indicators and sector aggregates."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from typing import Mapping, Sequence

from app.services.factor.types import ALL_FACTORS, FactorName
from app.services.quant_math import log_return


MacroPoint = tuple[datetime, float]
InstrumentReturnPoint = tuple[datetime, float]


def pct_change_series(values: Sequence[float]) -> list[float]:
    """Log-return style changes; first observation is 0."""
    if not values:
        return []
    if len(values) == 1:
        return [0.0]
    result = [0.0]
    for index in range(1, len(values)):
        prev = values[index - 1]
        curr = values[index]
        if prev <= 0.0 or curr <= 0.0:
            result.append(0.0)
        else:
            result.append(log_return(curr, prev))
    return result


def align_macro_to_timestamps(
    timestamps: Sequence[datetime],
    macro_points: Sequence[MacroPoint],
) -> list[float]:
    """Forward-fill macro levels onto ``timestamps`` and return pct changes."""
    if not timestamps:
        return []
    if not macro_points:
        return [0.0] * len(timestamps)

    sorted_points = sorted(macro_points, key=lambda item: item[0])
    levels: list[float] = []
    pointer = 0
    last_value = sorted_points[0][1]
    for timestamp in timestamps:
        while pointer + 1 < len(sorted_points) and sorted_points[pointer + 1][0] <= timestamp:
            pointer += 1
            last_value = sorted_points[pointer][1]
        if sorted_points[0][0] <= timestamp:
            levels.append(last_value)
        else:
            levels.append(sorted_points[0][1])
    return pct_change_series(levels)


def market_return_series(
    instrument_returns: Mapping[int, Sequence[InstrumentReturnPoint]],
) -> list[float]:
    """Cross-sectional average return per timestamp."""
    if not instrument_returns:
        return []
    length = len(next(iter(instrument_returns.values())))
    if length == 0:
        return []
    totals = [0.0] * length
    for series in instrument_returns.values():
        if len(series) != length:
            raise ValueError("All instrument return series must share timestamps.")
        for index, (_, value) in enumerate(series):
            totals[index] += value
    count = len(instrument_returns)
    return [value / count for value in totals]


def sector_return_series(
    timestamps: Sequence[datetime],
    peer_returns: Mapping[int, Sequence[InstrumentReturnPoint]],
    *,
    exclude_instrument_id: int | None = None,
) -> list[float]:
    """Equal-weight average return of sector peers at each timestamp."""
    if not peer_returns:
        return [0.0] * len(timestamps)
    length = len(timestamps)
    totals = [0.0] * length
    counts = [0] * length
    for instrument_id, series in peer_returns.items():
        if exclude_instrument_id is not None and instrument_id == exclude_instrument_id:
            continue
        if len(series) != length:
            raise ValueError("Peer return series length mismatch.")
        for index, (_, value) in enumerate(series):
            totals[index] += value
            counts[index] += 1
    return [totals[i] / counts[i] if counts[i] else 0.0 for i in range(length)]


def momentum_factor(market_returns: Sequence[float], lookback: int = 5) -> list[float]:
    """Trailing cumulative market return lagged by one period."""
    n = len(market_returns)
    result = [0.0] * n
    for index in range(lookback, n):
        result[index] = sum(market_returns[index - lookback : index])
    return result


def macro_shock_factor(
    vix_changes: Sequence[float],
    rate_changes: Sequence[float],
) -> list[float]:
    """Composite absolute macro move proxy."""
    if len(vix_changes) != len(rate_changes):
        raise ValueError("Macro shock inputs must have equal length.")
    return [abs(vix_changes[i]) + abs(rate_changes[i]) for i in range(len(vix_changes))]


def build_factor_return_matrix(
    *,
    timestamps: Sequence[datetime],
    instrument_returns: Mapping[int, Sequence[InstrumentReturnPoint]],
    sector_peers: Mapping[int, Sequence[InstrumentReturnPoint]],
    macro_by_code: Mapping[str, Sequence[MacroPoint]],
    exclude_instrument_id: int | None = None,
    momentum_lookback: int = 5,
) -> dict[FactorName, list[float]]:
    """Construct aligned factor return series for regression."""
    market = market_return_series(instrument_returns)
    sector = sector_return_series(timestamps, sector_peers, exclude_instrument_id=exclude_instrument_id)

    cpi = align_macro_to_timestamps(timestamps, macro_by_code.get("cpi", []))
    unemployment = align_macro_to_timestamps(timestamps, macro_by_code.get("unemployment", []))
    vix = align_macro_to_timestamps(timestamps, macro_by_code.get("vix", []))
    rates = align_macro_to_timestamps(
        timestamps,
        macro_by_code.get("rate_cb", []) or macro_by_code.get("rate_cb_us", []),
    )
    dxy = align_macro_to_timestamps(timestamps, macro_by_code.get("dxy", []))
    oil = align_macro_to_timestamps(timestamps, macro_by_code.get("oil_brent", []))

    growth = [-value for value in unemployment]
    value = [-value for value in cpi]
    macro_shock = macro_shock_factor(vix, rates)

    return {
        FactorName.MARKET_BETA: market,
        FactorName.SECTOR_FACTOR: sector,
        FactorName.MOMENTUM: momentum_factor(market, lookback=momentum_lookback),
        FactorName.VALUE: value,
        FactorName.GROWTH: growth,
        FactorName.VOLATILITY_FACTOR: vix,
        FactorName.RATES_SENSITIVITY: rates,
        FactorName.FX_SENSITIVITY: dxy,
        FactorName.COMMODITY_SENSITIVITY: oil,
        FactorName.MACRO_SHOCK_SENSITIVITY: macro_shock,
    }


def group_returns_by_sector(
    instrument_ids: Sequence[int],
    sector_by_instrument: Mapping[int, str],
    returns_by_instrument: Mapping[int, Sequence[InstrumentReturnPoint]],
) -> dict[str, dict[int, Sequence[InstrumentReturnPoint]]]:
    """Bucket instrument return series by sector label."""
    grouped: dict[str, dict[int, Sequence[InstrumentReturnPoint]]] = defaultdict(dict)
    for instrument_id in instrument_ids:
        sector = sector_by_instrument.get(instrument_id)
        if sector is None or instrument_id not in returns_by_instrument:
            continue
        grouped[sector][instrument_id] = returns_by_instrument[instrument_id]
    return grouped


def macro_points_from_rows(rows: Sequence[Mapping[str, object]]) -> dict[str, list[MacroPoint]]:
    """Convert ORM/dict macro rows into ``indicator_code -> [(time, value)]``."""
    grouped: dict[str, list[MacroPoint]] = defaultdict(list)
    for row in rows:
        code = str(row["indicator_code"])
        published_at = row["published_at"]
        if not isinstance(published_at, datetime):
            raise TypeError("published_at must be datetime.")
        value = row["value"]
        if isinstance(value, Decimal):
            numeric = float(value)
        else:
            numeric = float(value)
        grouped[code].append((published_at, numeric))
    for code in grouped:
        grouped[code].sort(key=lambda item: item[0])
    return grouped
