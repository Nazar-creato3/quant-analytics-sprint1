"""Honest 1–10 score: calibrated chance of beating the benchmark."""
from __future__ import annotations

from typing import Any, Mapping

from app.services.trading_engines.runtime.finrl_policy import policy_score


def probability_to_score_1_10(p_beat: float) -> int:
    """Map P(beat benchmark) to 1–10. 0.50 → 5, 0.75 → 8, 0.20 → 2."""
    clipped = min(1.0, max(0.0, float(p_beat)))
    return max(1, min(10, int(round(clipped * 10.0)) or 1))


def _block_score(values: Mapping[str, float], keys: tuple[str, ...], present_key: str) -> dict[str, Any] | None:
    if float(values.get(present_key, 0.0)) < 0.5:
        return None
    used = [float(values[k]) for k in keys if k in values]
    if not used:
        return None
    mean = sum(used) / len(used)
    p = 0.5 + 0.5 * max(-1.0, min(1.0, mean))
    return {"available": True, "score": probability_to_score_1_10(p), "p": round(p, 4)}


def build_market_beat(
    *,
    symbol: str,
    p_beat_20: float | None = None,
    p_beat_60: float | None = None,
    p_beat_1: float | None = None,
    p_beat_5: float | None = None,
    p_beat_21: float | None = None,
    features: Mapping[str, float],
    prices: list[float],
    live_accuracy: float | None = None,
    live_n: int = 0,
    model_accepted: bool = True,
) -> dict[str, Any]:
    """Product payload: 1d / 5d / 21d primary. 20/60 are aliases of 21 / optional long."""
    p21 = p_beat_21 if p_beat_21 is not None else p_beat_20
    p5 = p_beat_5 if p_beat_5 is not None else p21
    p1 = p_beat_1 if p_beat_1 is not None else p5
    p60 = p_beat_60 if p_beat_60 is not None else p21
    p1 = min(1.0, max(0.0, float(p1 or 0.5)))
    p5 = min(1.0, max(0.0, float(p5 or 0.5)))
    p21 = min(1.0, max(0.0, float(p21 or 0.5)))
    p20 = p21
    p60 = min(1.0, max(0.0, float(p60 or p21)))
    tech = _block_score(
        features,
        ("ret_5", "ret_21", "mom_z_21", "rsi_14"),
        "tech_present",
    ) or {
        "available": True,
        "score": probability_to_score_1_10(0.5 + 0.5 * float(features.get("ret_21", 0.0))),
        "p": None,
    }
    fund = _block_score(
        features,
        ("fmp_roe", "fmp_margin", "fmp_pe_inv"),
        "fund_present",
    )
    news = _block_score(features, ("news_sentiment",), "news_present")
    tier_c = _block_score(
        features,
        ("c_value_yield", "c_quality", "c_news_tone"),
        "c_tier_present",
    )

    from app.services.forecast.calibration import load_ece, platt_apply, score_1_10
    from app.services.risk.human_copy import market_beat_explanation

    ece = load_ece()
    a = float(ece.get("platt_a") or 1.0)
    b = float(ece.get("platt_b") or 0.0)
    p1 = platt_apply(p1, a=a, b=b)
    p5 = platt_apply(p5, a=a, b=b)
    p21 = platt_apply(p21, a=a, b=b)
    p20 = p21
    p60 = platt_apply(p60, a=a, b=b)
    score1, trusted1 = score_1_10(p1, ece_report=ece)
    score5, trusted5 = score_1_10(p5, ece_report=ece)
    score21, trusted21 = score_1_10(p21, ece_report=ece)
    score20, trusted20 = score21, trusted21
    score60, trusted60 = score_1_10(p60, ece_report=ece)
    try:
        from app.services.forecast.feature_kill import killed_blocks

        if "score" in killed_blocks():
            score1 = score5 = score21 = score20 = score60 = 5
            trusted1 = trusted5 = trusted21 = trusted20 = trusted60 = False
    except Exception:
        pass

    ppo = policy_score(prices, symbol=symbol)
    direction = int(ppo.get("direction") or 0)
    if direction > 0:
        timing = "enter"
        timing_ru = "входить"
    elif direction < 0:
        timing = "flat"
        timing_ru = "плоско / не наращивать"
    else:
        timing = "wait"
        timing_ru = "ждать"

    return {
        "symbol": symbol,
        "score_1": score1,
        "score_5": score5,
        "score_21": score21,
        "p_beat_1": round(p1, 4),
        "p_beat_5": round(p5, 4),
        "p_beat_21": round(p21, 4),
        "score_20": score20,
        "score_60": score60,
        "p_beat_20": round(p20, 4),
        "p_beat_60": round(p60, 4),
        "primary_horizons": [1, 5, 21],
        "score_trusted": trusted1 and trusted5 and trusted21,
        "ece": ece.get("ece"),
        "benchmark_hint": "SPY / IMOEX / BTC-USD по рынку бумаги",
        "explanation_ru": market_beat_explanation(
            score20=score20, p20=p20, trusted=bool(trusted20 and trusted60)
        ),
        "subscores": {
            "technical": tech,
            "fundamental": fund,
            "news": news,
            "tier_c": tier_c,
        },
        "selection": "lightgbm_panel_blend",
        "timing": timing,
        "timing_ru": timing_ru,
        "timing_source": ppo.get("mode"),
        "timing_trained": bool(ppo.get("trained")),
        "model_accepted": model_accepted,
        "live_accuracy": live_accuracy,
        "live_n": live_n,
    }


def market_beat_from_prices(
    symbol: str,
    prices: list[float],
    *,
    extras: Mapping[str, float] | None = None,
    news_sentiment: float = 0.0,
    order_book_imbalance: float = 0.0,
    live_accuracy: float | None = None,
    live_n: int = 0,
    volumes: list[float] | None = None,
    highs: list[float] | None = None,
    lows: list[float] | None = None,
    benchmark: list[float] | None = None,
) -> dict[str, Any]:
    from app.services.forecast.forecast_features import build_forecast_feature_row
    from app.services.forecast.gradient_boost_component import get_gradient_boost_component

    extra = dict(extras or {})
    features = build_forecast_feature_row(
        prices,
        news_sentiment=news_sentiment,
        order_book_imbalance=order_book_imbalance,
        extras=extra,
        volumes=volumes,
        highs=highs,
        lows=lows,
        benchmark=benchmark,
        allow_snapshot_fundamentals=True,
    )
    gb = get_gradient_boost_component()

    def _pred(hz: int):
        return gb.predict(
            prices,
            symbol=symbol,
            horizon=hz,
            extras=extra,
            volumes=volumes,
            highs=highs,
            lows=lows,
            benchmark=benchmark,
        )

    p1, p5, p21 = _pred(1), _pred(5), _pred(21)
    payload = build_market_beat(
        symbol=symbol,
        p_beat_1=p1.beat_probability,
        p_beat_5=p5.beat_probability,
        p_beat_21=p21.beat_probability,
        features=features,
        prices=prices,
        live_accuracy=live_accuracy,
        live_n=live_n,
        model_accepted=bool(p1.accepted and p5.accepted and p21.accepted),
    )
    from app.services.alpha.horizons import ALPHA_HORIZONS, latest_excess_map

    research = latest_excess_map(prices, benchmark)
    research["p_h1"] = round(float(p1.beat_probability), 4)
    research["dir_h1"] = int(p1.direction)
    research["p_h5"] = round(float(p5.beat_probability), 4)
    research["dir_h5"] = int(p5.direction)
    research["p_h21"] = round(float(p21.beat_probability), 4)
    research["dir_h21"] = int(p21.direction)
    payload["research_stack"] = research
    payload["primary_horizons"] = list(ALPHA_HORIZONS)
    return payload


async def market_beat_from_db(
    db,
    symbol: str,
    *,
    extras: Mapping[str, float] | None = None,
    news_sentiment: float = 0.0,
    live_accuracy: float | None = None,
    live_n: int = 0,
) -> dict[str, Any] | None:
    from app.services.forecast.excess_labels import benchmark_symbol_for
    from app.services.market_data.bars import get_bars_for_chart

    bars = await get_bars_for_chart(db, symbol, "1d", 260, force_refresh=False)
    closes = [float(b.close) for b in bars if getattr(b, "close", None) is not None]
    if len(closes) < 40:
        return None
    highs = [float(b.high) for b in bars if getattr(b, "high", None) is not None]
    lows = [float(b.low) for b in bars if getattr(b, "low", None) is not None]
    volumes = [float(getattr(b, "volume", 0) or 0) for b in bars]
    bbars = await get_bars_for_chart(db, benchmark_symbol_for(symbol), "1d", 260, force_refresh=False)
    bench = [float(b.close) for b in bbars if getattr(b, "close", None) is not None]
    return market_beat_from_prices(
        symbol,
        closes,
        extras=extras,
        news_sentiment=news_sentiment,
        live_accuracy=live_accuracy,
        live_n=live_n,
        volumes=volumes if len(volumes) == len(closes) else None,
        highs=highs if len(highs) == len(closes) else None,
        lows=lows if len(lows) == len(closes) else None,
        benchmark=bench or None,
    )
