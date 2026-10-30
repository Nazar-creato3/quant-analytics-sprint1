"""Optional VectorBT / FinRL overlays for forecast and maneuvers."""
from __future__ import annotations

from typing import Any, Sequence


def try_vectorbt_overlay(prices: Sequence[float], *, lookback: int = 10) -> dict[str, Any] | None:
    try:
        from app.services.trading_engines.backtest.vectorbt_engine import run_vectorbt_momentum

        return run_vectorbt_momentum(prices, lookback=lookback)
    except Exception:
        return None


def forecast_engine_overlays(prices: Sequence[float], *, symbol: str | None = None) -> dict[str, Any]:
    from app.services.trading_engines.runtime.finrl_policy import policy_score

    vbt = try_vectorbt_overlay(prices)
    finrl = policy_score(prices, symbol=symbol)
    return {
        "vectorbt": vbt,
        "finrl": finrl,
        "vectorbt_used": vbt is not None,
        "finrl_mode": finrl.get("mode"),
        "finrl_trained": bool(finrl.get("trained")),
    }


def maneuver_engine_overlays(prices: Sequence[float], *, symbol: str | None = None) -> dict[str, Any]:
    return forecast_engine_overlays(prices, symbol=symbol)
