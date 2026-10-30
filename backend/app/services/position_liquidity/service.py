from __future__ import annotations

from typing import Any

from app.services.position_liquidity.math import (
    corwin_schultz_spread,
    days_to_exit,
    median_adv,
    square_root_impact,
)
from app.services.qa.feature_flags import is_enabled

METHOD = "/methodology/liquidity"
STRESS_ADV = 0.5
NO_TRADES = "нет сделок"
RARE = "редкие сделки"

# Synthetic ADV (RUB) and sigma for demo / tests.
UNIVERSE: dict[str, dict[str, Any]] = {
    "SBER": {"turnovers20": [8_000_000] * 20, "sigma": 0.015, "value": 8000, "zero_days_60": 0, "bond": False, "hl": (101.0, 99.0)},
    "GAZP": {"turnovers20": [400_000] * 20, "sigma": 0.02, "value": 2000, "zero_days_60": 12, "bond": False, "hl": (102.0, 98.0)},
    "ILLIQ": {"turnovers20": [0.0] * 20, "sigma": 0.03, "value": 1000, "zero_days_60": 40, "bond": True, "hl": None},
}


def _row(ticker: str, spec: dict[str, Any], participation: float, *, stress: bool) -> dict[str, Any]:
    adv = median_adv(list(spec["turnovers20"]))
    if stress and adv is not None:
        adv = adv * STRESS_ADV
    value = float(spec["value"])
    days = days_to_exit(value, adv, participation)
    days5 = days_to_exit(value, adv, participation)  # same formula; capacity 5d = 5 * daily
    hl = spec.get("hl")
    half = 0.0
    if isinstance(hl, tuple) and len(hl) == 2:
        spread = corwin_schultz_spread(float(hl[0]), float(hl[1]))
        if spread is not None:
            half = spread / 2.0
    impact = square_root_impact(
        position_value=value, adv=adv, sigma_daily=spec.get("sigma"), half_spread=half
    )
    flags = []
    if adv is None:
        flags.append(NO_TRADES)
    if spec.get("bond") and int(spec.get("zero_days_60") or 0) >= 10:
        flags.append(RARE)
    sell_1d = None if adv is None else min(value, participation * adv)
    sell_5d = None if adv is None else min(value, 5 * participation * adv)
    return {
        "ticker": ticker,
        "adv_median_20": adv,
        "days_to_exit": days,
        "impact_frac": impact,
        "impact_rub": None if impact is None else impact * value,
        "sell_1d_rub": sell_1d,
        "sell_5d_rub": sell_5d,
        "zero_days_60": spec.get("zero_days_60"),
        "flags": flags,
        "status": NO_TRADES if adv is None else "ok",
        "spread_note": "оценка" if spec.get("hl") else "нет данных",
        "methodology": METHOD,
    }


def portfolio_liquidity(user_id: str, portfolio_id: str, participation: float = 0.1) -> dict[str, Any]:
    if not is_enabled("qa_position_liquidity"):
        return {"status": "flag_off"}
    if portfolio_id != "synth":
        real = _real_portfolio(user_id, portfolio_id, participation)
        if real is not None:
            return real
        return {
            "portfolio_id": portfolio_id,
            "user_id": user_id,
            "participation": participation,
            "issues": [],
            "share_1d": None,
            "share_5d": None,
            "fire_sale_1d_cost_rub": None,
            "stress": [],
            "methodology": METHOD,
            "as_of": None,
            "source": "нет данных",
            "data_status": "нет данных",
            "reason": "нет оборотов по позициям",
            "texts_key": "liquidity",
        }
    issues = [_row(t, spec, participation, stress=False) for t, spec in UNIVERSE.items()]
    nav = sum(float(UNIVERSE[r["ticker"]]["value"]) for r in issues)
    sell1 = sum(r["sell_1d_rub"] or 0 for r in issues)
    sell5 = sum(r["sell_5d_rub"] or 0 for r in issues)
    fire = sum((r["impact_rub"] or 0) for r in issues)
    stressed = [_row(r["ticker"], UNIVERSE[r["ticker"]], participation, stress=True) for r in issues]
    return {
        "portfolio_id": portfolio_id,
        "user_id": user_id,
        "participation": participation,
        "issues": issues,
        "share_1d": (sell1 / nav) if nav else None,
        "share_5d": (sell5 / nav) if nav else None,
        "fire_sale_1d_cost_rub": fire if issues else None,
        "stress_adv_factor": STRESS_ADV,
        "stress": stressed,
        "methodology": METHOD,
        "as_of": "2026-10-13",
        "source": "оценка",
        "data_status": "ok",
        "texts_key": "liquidity",
    }


def _real_portfolio(user_id: str, portfolio_id: str, participation: float) -> dict[str, Any] | None:
    """Liquidity of the user's own book from daily traded value in the price-history store."""
    from app.services.price_history import service as history
    from app.services.risk_engine.service import _holdings_from_book, _value_rub

    mode = "live" if portfolio_id == "live" else "paper"
    holdings = _holdings_from_book(user_id, mode)
    if not holdings:
        return None
    specs: dict[str, dict[str, Any]] = {}
    for h in holdings:
        ticker = str(h["ticker"])
        value = _value_rub(h)
        turn = history.turnovers_rub(ticker)
        if value is None or not turn:
            continue
        meta = history.info(ticker)
        specs[ticker] = {
            "turnovers20": turn,
            "sigma": history.daily_sigma(ticker),
            "value": value,
            "zero_days_60": history.zero_days(ticker),
            "bond": meta.get("market") == "bonds",
            "hl": history.last_high_low(ticker),
        }
    if not specs:
        return None
    issues = [_row(t, spec, participation, stress=False) for t, spec in specs.items()]
    nav = sum(float(s["value"]) for s in specs.values())
    sell1 = sum(r["sell_1d_rub"] or 0 for r in issues)
    sell5 = sum(r["sell_5d_rub"] or 0 for r in issues)
    fire = sum((r["impact_rub"] or 0) for r in issues)
    stressed = [_row(t, spec, participation, stress=True) for t, spec in specs.items()]
    days = [hit[0] for hit in (history.last(t) for t in specs) if hit]
    as_of = max(days) if days else None
    skipped = [str(h["ticker"]) for h in holdings if str(h["ticker"]) not in specs]
    return {
        "portfolio_id": portfolio_id,
        "user_id": user_id,
        "participation": participation,
        "issues": issues,
        "share_1d": (sell1 / nav) if nav else None,
        "share_5d": (sell5 / nav) if nav else None,
        "fire_sale_1d_cost_rub": fire if issues else None,
        "stress_adv_factor": STRESS_ADV,
        "stress": stressed,
        "methodology": METHOD,
        "as_of": as_of.isoformat() if hasattr(as_of, "isoformat") else as_of,
        "source": "оборот за 20 сессий, Московская биржа / биржи США",
        "data_status": "частично" if skipped else "ok",
        "reason": ("нет оборотов: " + ", ".join(skipped)) if skipped else None,
        "texts_key": "liquidity",
    }
