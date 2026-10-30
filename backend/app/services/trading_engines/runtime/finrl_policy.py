"""FinRL policy score: trained artifact first, then heuristic."""
from __future__ import annotations

from typing import Any, Sequence

from app.services.trading_engines.runtime.finrl_agent import infer_direction, load_policy


def _heuristic(close: list[float]) -> tuple[float, int, float]:
    rets = [close[i] / close[i - 1] - 1.0 for i in range(1, len(close))]
    window = rets[-15:]
    mean = sum(window) / len(window)
    var = sum((x - mean) ** 2 for x in window) / max(len(window) - 1, 1)
    vol = var**0.5
    score = mean / vol if vol > 1e-12 else 0.0
    direction = 1 if score > 0.15 else (-1 if score < -0.15 else 0)
    return score, direction, float(mean * 10.0)


def policy_score(prices: Sequence[float], *, symbol: str | None = None) -> dict[str, Any]:
    close = [float(p) for p in prices if p is not None]
    if len(close) < 16:
        return {
            "ok": False,
            "error": "insufficient_prices",
            "mode": "none",
            "trained": False,
        }

    from app.services.trading_engines.probes import probe_import

    pip = probe_import("finrl", "finrl")
    importable = bool(pip.get("importable"))
    policy = load_policy(symbol or "_default")
    if policy is not None:
        direction, strength = infer_direction(close, policy)
        mode = "trained_ppo" if policy.get("algo") == "ppo" else "trained_q_learning"
        return {
            "ok": True,
            "mode": mode,
            "trained": True,
            "score": float(strength),
            "direction": direction,
            "expected_return": float(strength) * 0.02,
            "symbol": policy.get("symbol"),
            "trained_at": policy.get("trained_at"),
            "train_greedy_return": policy.get("train_greedy_return"),
            "finrl_importable": importable,
            "finrl_version": pip.get("version"),
            "note": "Trained PPO/Q on Apex OHLCV (FinRL algorithm family, MIT). Risk gate still owns orders.",
        }

    score, direction, expected = _heuristic(close)
    return {
        "ok": True,
        "mode": "excess_return_heuristic",
        "trained": False,
        "score": float(score),
        "direction": direction,
        "expected_return": expected,
        "finrl_importable": importable,
        "finrl_version": pip.get("version"),
        "note": (
            "No saved policy. Train via POST /trading-engines/finrl/action {kind:train} "
            "or weekly forecast retrain. Installing the finrl pip package alone does not train."
        ),
    }
