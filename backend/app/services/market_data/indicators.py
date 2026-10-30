"""Chart overlays — one server implementation (Prompt 42).

SMA: arithmetic mean of the last ``period`` closes (inclusive).
EMA: seed = SMA of the first ``period`` closes, then k = 2/(period+1).
Bollinger: SMA ± width × population σ (divide by period, not period-1).
VWAP: cumulative typical price × volume / cumulative volume.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Sequence


def sma_series(closes: Sequence[float], period: int) -> list[float | None]:
    if period <= 0:
        return [None] * len(closes)
    out: list[float | None] = []
    acc = 0.0
    for i, value in enumerate(closes):
        acc += value
        if i >= period:
            acc -= closes[i - period]
        if i + 1 < period:
            out.append(None)
        else:
            out.append(acc / period)
    return out


def ema_series(closes: Sequence[float], period: int) -> list[float | None]:
    if period <= 0:
        return [None] * len(closes)
    out: list[float | None] = []
    k = 2.0 / (period + 1)
    ema: float | None = None
    for i, value in enumerate(closes):
        if i + 1 < period:
            out.append(None)
            continue
        if ema is None:
            ema = sum(closes[i - period + 1 : i + 1]) / period
        else:
            ema = value * k + ema * (1.0 - k)
        out.append(ema)
    return out


def bollinger(
    closes: Sequence[float],
    period: int = 20,
    width: float = 2.0,
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """SMA ± width × population σ. Rolling O(n) via sum / sum-of-squares."""
    mid = sma_series(closes, period)
    upper: list[float | None] = []
    lower: list[float | None] = []
    sum_x = 0.0
    sum_sq = 0.0
    for i, value in enumerate(closes):
        sum_x += value
        sum_sq += value * value
        if i >= period:
            old = closes[i - period]
            sum_x -= old
            sum_sq -= old * old
        m = mid[i]
        if m is None:
            upper.append(None)
            lower.append(None)
            continue
        # population variance: E[x^2] - (E[x])^2; clamp tiny negatives from float noise
        var = max(sum_sq / period - m * m, 0.0)
        std = var**0.5
        upper.append(m + width * std)
        lower.append(m - width * std)
    return mid, upper, lower


def vwap_series(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    volumes: Sequence[float],
) -> list[float | None]:
    pv = 0.0
    vol = 0.0
    out: list[float | None] = []
    n = min(len(highs), len(lows), len(closes), len(volumes))
    for i in range(n):
        typical = (highs[i] + lows[i] + closes[i]) / 3.0
        v = volumes[i] if volumes[i] > 0 else 1.0
        pv += typical * v
        vol += v
        out.append(pv / vol if vol > 0 else None)
    if len(closes) > n:
        out.extend([None] * (len(closes) - n))
    return out


def overlays_from_bars(bars: Sequence[dict[str, Any]]) -> dict[str, list[float | None]]:
    closes = [float(b["close"]) for b in bars]
    highs = [float(b.get("high", b["close"])) for b in bars]
    lows = [float(b.get("low", b["close"])) for b in bars]
    volumes = [float(b.get("volume") or 0) for b in bars]
    mid, upper, lower = bollinger(closes, 20, 2.0)
    return {
        "sma20": sma_series(closes, 20),
        "sma50": sma_series(closes, 50),
        "ema20": ema_series(closes, 20),
        "bb_mid": mid,
        "bb_upper": upper,
        "bb_lower": lower,
        "vwap": vwap_series(highs, lows, closes, volumes),
    }


def sma_decimal(closes: Sequence[Decimal], period: int) -> list[Decimal | None]:
    """Golden-path SMA in Decimal (tests)."""
    out: list[Decimal | None] = []
    for i in range(len(closes)):
        if i + 1 < period:
            out.append(None)
        else:
            window = closes[i - period + 1 : i + 1]
            out.append(sum(window, Decimal("0")) / Decimal(period))
    return out
