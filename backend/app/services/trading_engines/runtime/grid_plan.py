"""Hummingbot-style grid plan using Apex grid math (no Hummingbot process)."""
from __future__ import annotations

from typing import Any, Sequence


def propose_grid(
    *,
    symbol: str = "BTC-USD",
    mid: float | None = None,
    capital: float = 10_000.0,
    closes: Sequence[float] | None = None,
    risk_level: str = "medium",
) -> dict[str, Any]:
    if risk_level not in {"low", "medium", "high"}:
        risk_level = "medium"
    from app.services.grid.auto_calibrate import calculate_auto_grid
    from app.services.grid.levels import compute_grid_prices

    series = [float(p) for p in (closes or []) if p is not None]
    # GA16-310: never invent mid=100 or synthetic bars when both are missing.
    if mid is not None and float(mid) > 0:
        price = float(mid)
    elif series:
        price = series[-1]
    else:
        return {
            "ok": False,
            "error": "Нет рыночной цены и истории котировок для сетки.",
        }

    if price <= 0:
        return {"ok": False, "error": "Рыночная цена должна быть больше нуля."}

    auto = calculate_auto_grid(
        symbol,
        float(capital),
        price,
        series,
        risk_level=risk_level,  # type: ignore[arg-type]
    )
    cfg = auto.config
    levels = compute_grid_prices(cfg.lower_bound, cfg.upper_bound, cfg.num_levels, cfg.grid_type)
    return {
        "ok": True,
        "engine": "hummingbot_pattern",
        "symbol": symbol,
        "mid": price,
        "lower": cfg.lower_bound,
        "upper": cfg.upper_bound,
        "num_levels": cfg.num_levels,
        "grid_type": str(cfg.grid_type),
        "levels": levels,
        "capital": float(capital),
        "realized_volatility": auto.realized_volatility,
        "volatility_regime": auto.volatility_regime,
    }
