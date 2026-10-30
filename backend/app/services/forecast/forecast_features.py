"""Forecast features: OHLCV technicals (honest, many windows) + optional FMP/news."""
from __future__ import annotations

from typing import Mapping, Sequence

import numpy as np
import pandas as pd

from app.services.quant_math import historical_volatility
from app.services.regime.features import prices_to_returns, rolling_volatility
from app.services.forecast.tier_c_schema import TIER_C_FEATURE_COLUMNS

_WINDOWS = (2, 3, 4, 5, 6, 7, 8, 10, 13, 15, 21, 34, 42, 55, 63)

_TECH_DYNAMIC: tuple[str, ...] = tuple(
    f"{stat}_{w}"
    for w in _WINDOWS
    for stat in ("ret", "vol", "sma_gap", "max_gap", "min_gap", "mom_z", "down_share", "range")
)
_TECH_FIXED: tuple[str, ...] = (
    "rsi_7",
    "rsi_14",
    "rsi_21",
    "macd",
    "macd_hist",
    "bb_pos",
    "bb_width",
    "streak",
    "regime_bullish",
    "regime_bearish",
    "regime_shock",
    "tech_present",
    "returns_5d",
    "returns_20d",
    "volatility_20d",
    "momentum_z",
    "rsi_proxy",
    "atr_pct",
    "sector_relative_strength",
    "order_book_imbalance",
    "vol_ratio_20",
    "hl_range_14",
    "close_loc_14",
    "excess_ret_5",
    "excess_ret_21",
    "excess_ret_63",
    "bench_ret_21",
    "idio_ret_21",
    "cs_ret5_rank",
    "cs_ret21_rank",
    "cs_breadth",
)
_FUND: tuple[str, ...] = (
    "fmp_pe_inv",
    "fmp_roe",
    "fmp_roa",
    "fmp_de",
    "fmp_cr",
    "fmp_margin",
    "fmp_beta",
    "fmp_div",
    "fmp_log_mcap",
    "fund_present",
)
_NEWS: tuple[str, ...] = (
    "news_sentiment",
    "news_abs",
    "news_present",
    "earnings_proximity",
)

FORECAST_FEATURE_COLUMNS: tuple[str, ...] = (
    _TECH_DYNAMIC + _TECH_FIXED + _FUND + _NEWS + TIER_C_FEATURE_COLUMNS
)


def _rsi_proxy(returns: Sequence[float], window: int = 14) -> float:
    if len(returns) < window:
        return 0.5
    recent = returns[-window:]
    gains = sum(r for r in recent if r > 0)
    losses = abs(sum(r for r in recent if r < 0))
    if losses == 0:
        return 1.0
    rs = gains / losses
    return rs / (1 + rs)


def _window_ret(prices: Sequence[float], w: int) -> float:
    if len(prices) <= w:
        return 0.0
    a, b = float(prices[-w - 1]), float(prices[-1])
    if a <= 0:
        return 0.0
    return b / a - 1.0


def build_forecast_feature_row(
    prices: Sequence[float],
    *,
    sector_relative_strength: float = 0.0,
    order_book_imbalance: float = 0.0,
    news_sentiment: float = 0.0,
    earnings_days_until: int | None = None,
    regime_label: str = "choppy_range",
    extras: Mapping[str, float] | None = None,
    volumes: Sequence[float] | None = None,
    highs: Sequence[float] | None = None,
    lows: Sequence[float] | None = None,
    benchmark: Sequence[float] | None = None,
    allow_snapshot_fundamentals: bool = True,
) -> dict[str, float]:
    """One feature vector. Snapshot FMP/news stay off in training (look-ahead)."""
    row = {col: 0.0 for col in FORECAST_FEATURE_COLUMNS}
    if len(prices) < 10:
        return row

    px = [float(p) for p in prices]
    returns = prices_to_returns(px)
    for w in _WINDOWS:
        sl = px[-w:] if len(px) >= w else px
        last = px[-1]
        mean = sum(sl) / len(sl)
        peak = max(sl)
        trough = min(sl)
        ret = _window_ret(px, w)
        vol = historical_volatility(returns[-w:]) if len(returns) >= w else 0.0
        rets_w = returns[-w:] if len(returns) >= w else returns
        down = sum(1 for r in rets_w if r < 0) / max(len(rets_w), 1)
        row[f"ret_{w}"] = ret
        row[f"vol_{w}"] = vol
        row[f"sma_gap_{w}"] = (last / mean - 1.0) if mean else 0.0
        row[f"max_gap_{w}"] = (last / peak - 1.0) if peak else 0.0
        row[f"min_gap_{w}"] = (last / trough - 1.0) if trough else 0.0
        row[f"mom_z_{w}"] = ret / vol if vol > 1e-8 else 0.0
        row[f"down_share_{w}"] = float(down)
        row[f"range_{w}"] = ((peak - trough) / last) if last else 0.0

    row["rsi_7"] = _rsi_proxy(returns, 7)
    row["rsi_14"] = _rsi_proxy(returns, 14)
    row["rsi_21"] = _rsi_proxy(returns, 21)
    row["rsi_proxy"] = row["rsi_14"]

    ema12 = _ema(px, 12)
    ema26 = _ema(px, 26)
    row["macd"] = ema12 - ema26
    row["macd_hist"] = row["macd"] - _ema([ema12 - ema26], 9) if len(px) > 26 else row["macd"]

    sl20 = px[-20:] if len(px) >= 20 else px
    mid = sum(sl20) / len(sl20)
    var = sum((x - mid) ** 2 for x in sl20) / max(len(sl20) - 1, 1)
    sd = var**0.5
    row["bb_width"] = (2 * sd / mid) if mid else 0.0
    row["bb_pos"] = ((px[-1] - (mid - 2 * sd)) / (4 * sd)) if sd > 1e-12 else 0.5

    streak = 0
    for i in range(len(px) - 1, 0, -1):
        if px[i] > px[i - 1]:
            streak += 1
        else:
            break
    row["streak"] = float(streak)

    row["returns_5d"] = row["ret_5"]
    row["returns_20d"] = row["ret_21"]
    vol20 = rolling_volatility(returns, min(20, len(returns)))
    row["volatility_20d"] = vol20[-1] if vol20 else row["vol_21"]
    row["momentum_z"] = row["mom_z_5"]
    row["atr_pct"] = row["volatility_20d"]
    row["sector_relative_strength"] = float(sector_relative_strength)
    row["order_book_imbalance"] = float(order_book_imbalance)
    row["regime_bullish"] = 1.0 if regime_label == "bullish_trend" else 0.0
    row["regime_bearish"] = 1.0 if regime_label == "bearish_trend" else 0.0
    row["regime_shock"] = 1.0 if regime_label == "high_volatility_shock" else 0.0
    row["tech_present"] = 1.0

    if volumes and len(volumes) == len(px):
        vs = [max(float(v), 0.0) for v in volumes]
        mean20 = sum(vs[-20:]) / max(len(vs[-20:]), 1)
        row["vol_ratio_20"] = (vs[-1] / mean20) if mean20 > 1e-12 else 0.0
    if highs and lows and len(highs) == len(px) and len(lows) == len(px):
        hs = [float(x) for x in highs]
        ls = [float(x) for x in lows]
        n = min(14, len(px))
        ranges = [(hs[-i] - ls[-i]) / px[-i] for i in range(1, n + 1) if px[-i] > 0]
        row["hl_range_14"] = sum(ranges) / len(ranges) if ranges else 0.0
        peak_h = max(hs[-n:])
        trough_l = min(ls[-n:])
        span = peak_h - trough_l
        row["close_loc_14"] = ((px[-1] - trough_l) / span) if span > 1e-12 else 0.5

    if benchmark and len(benchmark) >= 10:
        b = list(benchmark)
        if len(b) > len(px):
            b = b[-len(px) :]
        elif len(b) < len(px):
            b = [b[0]] * (len(px) - len(b)) + b
        for w, key in ((5, "excess_ret_5"), (21, "excess_ret_21"), (63, "excess_ret_63")):
            row[key] = _window_ret(px, w) - _window_ret(b, w)
        row["bench_ret_21"] = _window_ret(b, 21)
        a_rets = [px[i] / px[i - 1] - 1.0 for i in range(1, len(px)) if px[i - 1] > 0]
        b_rets = [b[i] / b[i - 1] - 1.0 for i in range(1, len(b)) if b[i - 1] > 0]
        w = min(63, len(a_rets), len(b_rets))
        beta = 1.0
        if w >= 20:
            aa = np.asarray(a_rets[-w:], dtype=float)
            bb = np.asarray(b_rets[-w:], dtype=float)
            var_b = float(np.var(bb))
            if var_b > 1e-12:
                beta = float(np.cov(aa, bb)[0, 1] / var_b)
        row["idio_ret_21"] = _window_ret(px, 21) - beta * _window_ret(b, 21)

    extra = extras or {}
    row["cs_ret5_rank"] = float(extra.get("cs_ret5_rank", 0.0))
    row["cs_ret21_rank"] = float(extra.get("cs_ret21_rank", 0.0))
    row["cs_breadth"] = float(extra.get("cs_breadth", 0.0))

    earnings_prox = 0.0
    if earnings_days_until is not None:
        earnings_prox = max(0.0, 1.0 - min(int(earnings_days_until), 30) / 30.0)
    row["earnings_proximity"] = earnings_prox if allow_snapshot_fundamentals else 0.0
    if allow_snapshot_fundamentals:
        row["news_sentiment"] = float(news_sentiment)
        row["news_abs"] = abs(float(news_sentiment))
        row["news_present"] = 1.0 if abs(float(news_sentiment)) > 1e-9 else 0.0
        for key in _FUND:
            if key in extra:
                row[key] = float(extra[key])
        if row.get("fund_present", 0.0) < 0.5 and any(
            abs(row[k]) > 1e-12 for k in _FUND if k != "fund_present"
        ):
            row["fund_present"] = 1.0
        for key in TIER_C_FEATURE_COLUMNS:
            if key in extra:
                row[key] = float(extra[key])
        if row.get("c_tier_present", 0.0) < 0.5 and any(
            abs(row[k]) > 1e-12 for k in TIER_C_FEATURE_COLUMNS if k != "c_tier_present"
        ):
            row["c_tier_present"] = 1.0
    try:
        from app.services.forecast.feature_kill import killed_blocks

        dead = killed_blocks()
        if "fundamental" in dead:
            for key in _FUND:
                row[key] = 0.0
        if "news" in dead:
            for key in _NEWS:
                row[key] = 0.0
    except Exception:
        pass
    return row


def _ema(values: Sequence[float], span: int) -> float:
    if not values:
        return 0.0
    alpha = 2.0 / (span + 1.0)
    acc = float(values[0])
    for v in values[1:]:
        acc = alpha * float(v) + (1.0 - alpha) * acc
    return acc


def build_feature_matrix(
    prices: Sequence[float],
    *,
    enrichments: Sequence[Mapping[str, float]] | None = None,
    regime_labels: Sequence[str] | None = None,
    min_history: int = 30,
    volumes: Sequence[float] | None = None,
    highs: Sequence[float] | None = None,
    lows: Sequence[float] | None = None,
    benchmark: Sequence[float] | None = None,
    allow_snapshot_fundamentals: bool = False,
    symbol: str | None = None,
    dates: Sequence[str] | None = None,
) -> pd.DataFrame:
    """OHLCV is sliced to i. Fund/news only from extras_as_of(symbol, dates[i])."""
    rows: list[dict[str, float]] = []
    dated = (
        bool(symbol)
        and dates is not None
        and len(dates) == len(prices)
    )
    for i in range(min_history, len(prices)):
        extra: dict[str, float] = {}
        allow = allow_snapshot_fundamentals
        if dated:
            from app.services.forecast.asof_store import extras_as_of

            extra = extras_as_of(str(symbol), str(dates[i])[:10])
            allow = bool(extra)
        elif enrichments and i < len(enrichments) and allow_snapshot_fundamentals:
            extra = dict(enrichments[i])
        regime = regime_labels[i] if regime_labels and i < len(regime_labels) else "choppy_range"
        rows.append(
            build_forecast_feature_row(
                prices[: i + 1],
                sector_relative_strength=float(extra.get("sector_relative_strength", 0.0)),
                order_book_imbalance=0.0,
                news_sentiment=0.0 if not allow else float(extra.get("news_sentiment", 0.0)),
                earnings_days_until=None,
                regime_label=regime,
                extras=extra,
                volumes=volumes[: i + 1] if volumes else None,
                highs=highs[: i + 1] if highs else None,
                lows=lows[: i + 1] if lows else None,
                benchmark=benchmark[: i + 1] if benchmark else None,
                allow_snapshot_fundamentals=allow,
            )
        )
    return pd.DataFrame(rows, columns=list(FORECAST_FEATURE_COLUMNS))
