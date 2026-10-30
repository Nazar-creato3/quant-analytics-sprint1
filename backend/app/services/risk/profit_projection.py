"""
Honest profit / horizon projections for maneuvers (trading-platform blueprint).

Expected P&L ranges are tied to volatility and remaining time — not to the
take-profit notional alone. TP profit is shown separately with an estimated
hit probability before horizon expiry.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, Protocol


class IntervalForecastLike(Protocol):
    horizon_days: int
    p10: float
    p90: float
    rolling_volatility: float


from app.services.portfolio.position_analytics import horizon_to_seconds

Z_90 = 1.645  # ~90% two-sided interval on cumulative return (matches hierarchy)


def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def horizon_to_days(time_horizon: str | None) -> float | None:
    seconds = horizon_to_seconds(time_horizon)
    if seconds is None:
        return None
    return seconds / 86_400.0


@dataclass(frozen=True, slots=True)
class ProfitProjection:
    """Creation-time or live enrichment projection."""

    expected_return_low_pct: float
    expected_return_high_pct: float
    expected_pnl_low: float
    expected_pnl_high: float
    tp_profit_usd: float
    tp_hit_probability: float
    forecast_horizon_days: float
    remaining_days: float
    data_source: Literal["hierarchy", "volatility_proxy", "insufficient"]
    disclosure_ru: str


def _infer_daily_vol(
    entry_price: float,
    stop_loss: float | None,
    daily_vol: float | None,
) -> float:
    if daily_vol is not None and daily_vol > 0:
        return daily_vol
    if entry_price > 0 and stop_loss is not None:
        # Stop is placed at ~2× ATR; ATR/price ≈ half the stop distance / entry.
        stop_dist = abs(entry_price - stop_loss) / entry_price
        proxy = stop_dist / 2.0
        if proxy > 1e-6:
            return proxy
    return 0.02  # conservative default when history/ATR unavailable (common for thin crypto feeds)


def _cumulative_band(
    daily_vol: float,
    horizon_days: float,
    interval: IntervalForecastLike | None,
) -> tuple[float, float, float]:
    """Return (p10, p50, p90) as decimal cumulative simple returns over horizon_days."""
    days = max(horizon_days, 1.0 / 24.0)
    if interval and interval.rolling_volatility > 0:
        ref = max(float(interval.horizon_days), 1.0)
        vol = interval.rolling_volatility
        scale = math.sqrt(days / ref)
        p10 = interval.p10 * scale
        p90 = interval.p90 * scale
        source_vol = vol
    else:
        sigma = daily_vol * math.sqrt(days)
        p10 = -sigma * Z_90
        p90 = sigma * Z_90
        source_vol = daily_vol

    p50 = (p10 + p90) / 2.0
    if source_vol <= 0:
        return 0.0, 0.0, 0.0
    return p10, p50, p90


def _directional_band(
    direction: str,
    p10: float,
    p50: float,
    p90: float,
) -> tuple[float, float, float]:
    """Map price-return band to position P&L return (decimal)."""
    d = direction.lower()
    if d == "short":
        return (-p90, -p50, -p10)
    return (p10, p50, p90)


def tp_return_decimal(direction: str, entry_price: float, take_profit: float) -> float | None:
    if entry_price <= 0 or take_profit <= 0:
        return None
    if direction.lower() == "short":
        return (entry_price - take_profit) / entry_price
    return (take_profit - entry_price) / entry_price


def tp_hit_probability(
    direction: str,
    entry_price: float,
    take_profit: float,
    daily_vol: float,
    remaining_days: float,
    drift_return: float,
) -> float:
    """
    Probability that cumulative return reaches TP before horizon,
    using a lognormal-style normal approximation on cumulative return.
    """
    tp_ret = tp_return_decimal(direction, entry_price, take_profit)
    if tp_ret is None or remaining_days <= 0:
        return 0.0
    sigma = daily_vol * math.sqrt(max(remaining_days, 1.0 / 24.0))
    if sigma <= 1e-12:
        return 1.0 if drift_return >= tp_ret else 0.0
    z = (tp_ret - drift_return) / sigma
    return max(0.0, min(1.0, 1.0 - _normal_cdf(z)))


def compute_profit_projection(
    *,
    direction: str,
    entry_price: float,
    take_profit: float | None,
    stop_loss: float | None,
    position_size_usd: float,
    time_horizon: str | None,
    daily_vol: float | None = None,
    interval_forecast: IntervalForecastLike | None = None,
    momentum_sign: int = 0,
    round_trip_fees_usd: float = 0.0,
    remaining_days: float | None = None,
) -> ProfitProjection | None:
    if entry_price <= 0 or position_size_usd <= 0:
        return None

    horizon_days = horizon_to_days(time_horizon)
    if horizon_days is None:
        horizon_days = 5.0

    rem = remaining_days if remaining_days is not None else horizon_days
    rem = max(rem, 0.0)

    vol = _infer_daily_vol(entry_price, stop_loss, daily_vol)
    source: Literal["hierarchy", "volatility_proxy", "insufficient"] = (
        "hierarchy" if interval_forecast else "volatility_proxy"
    )
    if vol <= 0:
        source = "insufficient"

    p10, p50, p90 = _cumulative_band(vol, rem if rem > 0 else horizon_days, interval_forecast)
    if momentum_sign > 0:
        p50 = max(p50, 0.0)
    elif momentum_sign < 0:
        p50 = min(p50, 0.0)

    ret_lo, ret_mid, ret_hi = _directional_band(direction, p10, p50, p90)

    tp_ret = tp_return_decimal(direction, entry_price, take_profit or 0.0)
    if tp_ret is not None:
        ret_hi = min(ret_hi, tp_ret)
        ret_lo = max(ret_lo, -abs(tp_ret) * 1.2)

    ret_lo_pct = ret_lo * 100.0
    ret_hi_pct = ret_hi * 100.0

    pnl_low = position_size_usd * ret_lo - round_trip_fees_usd
    pnl_high = position_size_usd * ret_hi - round_trip_fees_usd

    tp_profit = 0.0
    tp_prob = 0.0
    if take_profit and tp_ret is not None:
        tp_profit = position_size_usd * tp_ret - round_trip_fees_usd
        tp_prob = tp_hit_probability(
            direction, entry_price, take_profit, vol, rem if rem > 0 else horizon_days, ret_mid
        )

    crypto_note = ""
    if interval_forecast is None:
        crypto_note = (
            " Прогноз иерархии недоступен — диапазон по волатильности (ATR/стоп); "
            "для части крипто-тикеров история может быть неполной."
        )

    disclosure = (
        f"Ожидаемый P&L на оставшийся срок (~{rem:.1f} дн.): "
        f"{ret_lo_pct:+.1f}%…{ret_hi_pct:+.1f}% "
        f"(${pnl_low:,.0f}…${pnl_high:,.0f}). "
        f"Полный профит при TP ${tp_profit:,.0f} — оценка достижимости до экспирации "
        f"{tp_prob:.0%}.{crypto_note}"
    )

    return ProfitProjection(
        expected_return_low_pct=round(ret_lo_pct, 2),
        expected_return_high_pct=round(ret_hi_pct, 2),
        expected_pnl_low=round(pnl_low, 2),
        expected_pnl_high=round(pnl_high, 2),
        tp_profit_usd=round(tp_profit, 2),
        tp_hit_probability=round(tp_prob, 4),
        forecast_horizon_days=round(horizon_days, 2),
        remaining_days=round(rem, 2),
        data_source=source,
        disclosure_ru=disclosure.strip(),
    )


def parse_interval_from_cache(cached: dict | None) -> IntervalForecastLike | None:
    if not cached:
        return None
    raw = cached.get("interval_forecast")
    if not isinstance(raw, dict):
        return None
    try:

        @dataclass(frozen=True, slots=True)
        class _Interval:
            horizon_days: int
            p10: float
            p90: float
            rolling_volatility: float
            confidence_multiplier: float = Z_90

        p10 = float(raw.get("p10") or 0.0)
        p90 = float(raw.get("p90") or 0.0)
        vol = float(raw.get("rolling_volatility") or 0.0)
        if vol <= 0 and p90 != p10:
            # Cache historically omitted σ; recover from 90% band width.
            z = float(raw.get("confidence_multiplier") or Z_90) or Z_90
            vol = max(0.0, abs(p90 - p10) / (2.0 * z))
        return _Interval(
            horizon_days=int(raw.get("horizon_days") or 10),
            p10=p10,
            p90=p90,
            rolling_volatility=vol,
            confidence_multiplier=float(raw.get("confidence_multiplier") or Z_90),
        )
    except (TypeError, ValueError):
        return None
