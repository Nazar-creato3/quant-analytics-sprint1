"""Cross-sectional style factor z-scores (spec Section 1)."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Sequence

from app.services.quant_math import historical_volatility, log_return

STYLE_FACTOR_NAMES: tuple[str, ...] = (
    "value",
    "momentum",
    "size",
    "quality",
    "low_vol",
    "growth",
    "liquidity",
)

_TRADING_DAYS_YEAR = 252
_MOMENTUM_SKIP = 21
_MOMENTUM_WINDOW = 252


@dataclass(frozen=True, slots=True)
class RawStyleSignals:
    """Unstandardized factor inputs before z-scoring."""

    value: float | None = None
    momentum: float | None = None
    size: float | None = None
    quality: float | None = None
    low_vol: float | None = None
    growth: float | None = None
    liquidity: float | None = None

    def as_dict(self) -> dict[str, float | None]:
        return {
            "value": self.value,
            "momentum": self.momentum,
            "size": self.size,
            "quality": self.quality,
            "low_vol": self.low_vol,
            "growth": self.growth,
            "liquidity": self.liquidity,
        }


def cross_sectional_zscore(values: Mapping[str, float | None]) -> dict[str, float | None]:
    """z_i = (x_i - mean) / std across non-null observations."""
    numeric = {key: float(value) for key, value in values.items() if value is not None and math.isfinite(value)}
    if len(numeric) < 2:
        if len(numeric) == 1:
            key = next(iter(numeric))
            return {factor: (0.0 if factor == key else None) for factor in values}
        return {key: None for key in values}

    mean = sum(numeric.values()) / len(numeric)
    variance = sum((value - mean) ** 2 for value in numeric.values()) / (len(numeric) - 1)
    std = math.sqrt(variance) if variance > 0 else 0.0

    result: dict[str, float | None] = {}
    for key in values:
        raw = values.get(key)
        if raw is None or not math.isfinite(raw):
            result[key] = None
        elif std <= 1e-12:
            result[key] = 0.0
        else:
            result[key] = round((float(raw) - mean) / std, 4)
    return result


def time_series_zscore(series: Sequence[float], *, window: int = 60) -> float | None:
    """Z-score the last observation against its trailing window."""
    if len(series) < window or window < 2:
        return None
    window_slice = list(series[-window:])
    last = window_slice[-1]
    mean = sum(window_slice) / len(window_slice)
    variance = sum((value - mean) ** 2 for value in window_slice) / (len(window_slice) - 1)
    std = math.sqrt(variance) if variance > 0 else 0.0
    if std <= 1e-12:
        return 0.0
    return round((last - mean) / std, 4)


def _returns_from_prices(prices: Sequence[float]) -> list[float]:
    if len(prices) < 2:
        return []
    returns: list[float] = []
    for index in range(1, len(prices)):
        prev, curr = prices[index - 1], prices[index]
        if prev <= 0 or curr <= 0:
            returns.append(0.0)
        else:
            returns.append(log_return(curr, prev))
    return returns


def _momentum_12_1(prices: Sequence[float]) -> float | None:
    """12-month return excluding the most recent month (log-return sum)."""
    returns = _returns_from_prices(prices)
    needed = _MOMENTUM_WINDOW
    if len(returns) < needed:
        return None
    trailing = returns[-needed:]
    if len(trailing) <= _MOMENTUM_SKIP:
        return None
    return sum(trailing[: -_MOMENTUM_SKIP])


def _low_vol_signal(prices: Sequence[float], *, window: int = 60) -> float | None:
    returns = _returns_from_prices(prices)
    if len(returns) < window:
        return None
    vol = historical_volatility(returns[-window:])
    if vol <= 0:
        return None
    annualized = vol * math.sqrt(_TRADING_DAYS_YEAR)
    return -annualized


def _liquidity_signal(
    *,
    avg_volume: float | None,
    market_cap: float | None,
    prices: Sequence[float],
    volumes: Sequence[float],
) -> float | None:
    if avg_volume is not None and avg_volume > 0 and market_cap is not None and market_cap > 0:
        return avg_volume / market_cap
    if volumes and prices:
        recent_vol = sum(float(v) for v in volumes[-20:]) / min(20, len(volumes))
        if recent_vol > 0:
            return math.log1p(recent_vol)
    return None


def compute_raw_style_signals(
    *,
    prices: Sequence[float],
    volumes: Sequence[float] | None = None,
    fundamentals: Mapping[str, float | None] | None = None,
) -> RawStyleSignals:
    """Derive raw style inputs from OHLCV closes and optional fundamentals."""
    fund = fundamentals or {}
    pe = fund.get("pe_ratio")
    value: float | None = None
    if pe is not None and pe > 0:
        value = 1.0 / float(pe)

    market_cap = fund.get("market_cap")
    size: float | None = None
    if market_cap is not None and market_cap > 0:
        size = -math.log(float(market_cap))

    roe = fund.get("roe")
    quality: float | None = float(roe) if roe is not None else None

    growth_raw = fund.get("revenue_growth") or fund.get("earnings_growth")
    growth: float | None = float(growth_raw) if growth_raw is not None else None
    if growth is None and fund.get("eps") is not None and len(prices) >= 2:
        eps = float(fund["eps"])
        if eps > 0 and prices[-1] > 0:
            growth = eps / prices[-1]

    avg_volume = fund.get("average_volume") or fund.get("avg_volume")
    vols = volumes or []
    liquidity = _liquidity_signal(
        avg_volume=float(avg_volume) if avg_volume is not None else None,
        market_cap=float(market_cap) if market_cap is not None else None,
        prices=prices,
        volumes=vols,
    )

    return RawStyleSignals(
        value=value,
        momentum=_momentum_12_1(prices),
        size=size,
        quality=quality,
        low_vol=_low_vol_signal(prices),
        growth=growth,
        liquidity=liquidity,
    )


def compute_style_factor_exposures(
    *,
    target_signals: RawStyleSignals,
    peer_signals: Sequence[RawStyleSignals] | None = None,
    prices: Sequence[float] | None = None,
) -> dict[str, float | None]:
    """
    Cross-sectional z-scores when peers exist; otherwise time-series fallback
    for momentum/low_vol and explicit nulls for missing fundamentals.
    """
    all_signals = [target_signals, *(peer_signals or [])]
    combined: dict[str, list[float | None]] = {name: [] for name in STYLE_FACTOR_NAMES}
    for signals in all_signals:
        for name, value in signals.as_dict().items():
            combined[name].append(value)

    cross_section: dict[str, float | None] = {}
    for name in STYLE_FACTOR_NAMES:
        values = {f"peer_{idx}": val for idx, val in enumerate(combined[name])}
        zscores = cross_sectional_zscore(values)
        cross_section[name] = zscores.get("peer_0")

    if peer_signals:
        return cross_section

    if prices and len(prices) >= _MOMENTUM_WINDOW:
        returns = _returns_from_prices(prices)
        mom_series: list[float] = []
        for end in range(_MOMENTUM_WINDOW, len(returns) + 1):
            window_prices = [1.0]
            for r in returns[end - _MOMENTUM_WINDOW : end - _MOMENTUM_SKIP]:
                window_prices.append(window_prices[-1] * math.exp(r))
            mom_series.append(sum(returns[end - _MOMENTUM_WINDOW : end - _MOMENTUM_SKIP]))
        if mom_series:
            cross_section["momentum"] = time_series_zscore(mom_series)

        vol_series: list[float] = []
        for end in range(60, len(returns) + 1):
            vol_series.append(-historical_volatility(returns[end - 60 : end]) * math.sqrt(_TRADING_DAYS_YEAR))
        if vol_series:
            cross_section["low_vol"] = time_series_zscore(vol_series)

    return cross_section


def merge_regression_betas(
    style_exposures: Mapping[str, float | None],
    regression_betas: Mapping[str, float],
) -> dict[str, float | None]:
    """Overlay FactorEngine regression betas where style z-scores are missing."""
    merged: dict[str, float | None] = {key: style_exposures.get(key) for key in STYLE_FACTOR_NAMES}
    alias_map = {
        "momentum": "momentum",
        "value": "value",
        "growth": "growth",
        "low_vol": "volatility_factor",
        "quality": "quality",
        "size": "size",
        "liquidity": "liquidity",
    }
    for style_key, reg_key in alias_map.items():
        if merged.get(style_key) is None and reg_key in regression_betas:
            merged[style_key] = round(float(regression_betas[reg_key]), 4)
    return merged
