"""Portfolio futures risk and hedge calculator."""
from __future__ import annotations

from time import perf_counter
from typing import Any

from app.services.explanations.service import filter_wording
from app.services.futures_risk.math import (
    cushion_to_margin_call,
    hedge_contracts,
    notional,
    portfolio_leverage,
    residual_risk,
)
from app.services.qa.feature_flags import is_enabled


def explain(
    *,
    positions: list[dict[str, Any]],
    liquid_nav: float | None,
    min_margin: float | None = None,
    initial_margin: float | None = None,
    beta: float | None = None,
    hedge_share: float = 0.0,
    hedge_fut_price: float | None = None,
    hedge_point_value: float | None = None,
    portfolio_vol: float | None = None,
    index_vol: float | None = None,
) -> dict[str, Any]:
    started = perf_counter()
    if not is_enabled("qa_futures_risk"):
        return {"data_status": "нет данных", "reason": "нет данных"}
    missing: list[str] = []
    rows: list[dict[str, Any]] = []
    notionals: list[float] = []
    signed = 0.0
    for pos in positions:
        ticker = str(pos.get("ticker") or "").upper()
        qty = float(pos.get("qty") or 0)
        price = pos.get("price")
        pv = pos.get("point_value")
        if price is None or pv is None:
            missing.append(ticker or "без тикера")
            rows.append({"ticker": ticker, "notional": None})
            continue
        nom = notional(qty=qty, price=float(price), point_value=float(pv))
        notionals.append(nom)
        signed += nom if qty >= 0 else -nom
        hold_cost = pos.get("funding_30d")
        rows.append(
            {
                "ticker": ticker,
                "notional": nom,
                "initial_margin": pos.get("initial_margin"),
                "hold_cost_30d": hold_cost,
                "days_to_expiry": pos.get("days_to_expiry"),
                "basis": pos.get("basis"),
                "perpetual": bool(pos.get("perpetual")),
            }
        )
    if liquid_nav is None:
        missing.append("ликвидная стоимость")
    lev = portfolio_leverage(notionals=notionals, liquid_nav=float(liquid_nav or 0))
    cushion = None
    if min_margin is None:
        missing.append("минимальная маржа")
    elif liquid_nav is not None:
        cushion = cushion_to_margin_call(
            liquid_nav=float(liquid_nav),
            min_margin=float(min_margin),
            signed_notional=signed,
        )
    hedge = None
    if hedge_share and beta is not None and hedge_fut_price and hedge_point_value and liquid_nav:
        n = hedge_contracts(
            beta=float(beta),
            portfolio_value=float(liquid_nav),
            hedge_share=float(hedge_share),
            fut_price=float(hedge_fut_price),
            point_value=float(hedge_point_value),
        )
        hedge_go = None
        if n is not None and positions:
            go = positions[0].get("initial_margin")
            if go is not None:
                hedge_go = abs(n) * float(go)
        resid = None
        if portfolio_vol is not None and index_vol is not None and beta is not None:
            resid = residual_risk(portfolio_vol=float(portfolio_vol), beta=float(beta), index_vol=float(index_vol))
        hedge = {
            "contracts": n,
            "initial_margin": hedge_go,
            "residual_vol": resid,
            "caption": "расчёт для понимания, не рекомендация",
        }
        if filter_wording(hedge["caption"]):
            hedge["caption"] = "нет данных"
    status = "нет данных" if not rows and missing else ("частично" if missing else "ok")
    return {
        "data_status": status,
        "reason": None if not missing else "пропущено: " + ", ".join(missing),
        "rows": rows,
        "leverage": lev,
        "cushion": cushion,
        "liquid_nav": liquid_nav,
        "min_margin": min_margin,
        "initial_margin": initial_margin,
        "hedge": hedge,
        "methodology": "/methodology/futures",
        "elapsed_ms": round((perf_counter() - started) * 1000.0, 3),
    }
