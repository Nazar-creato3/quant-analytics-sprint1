"""Train / load a FinRL-style trading policy (Q-learning; no FinRL pip required).

Official `finrl` + Stable-Baselines3 is optional. The contract is the same:
train on OHLCV closes → persist → infer direction for forecast/maneuvers.
"""
from __future__ import annotations

import json
import os
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

_N_RET_BINS = 5
_ACTIONS = 3  # 0 flat, 1 long, 2 short
_FEE = 0.0005


def model_dir() -> Path:
    override = (os.getenv("FINRL_MODEL_DIR") or "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[4] / "models" / "finrl"


def _safe_symbol(symbol: str) -> str:
    raw = (symbol or "_default").strip().upper() or "_DEFAULT"
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in raw)


def model_path(symbol: str) -> Path:
    return model_dir() / f"{_safe_symbol(symbol)}.json"


def _closes(prices: Sequence[float]) -> list[float]:
    return [float(p) for p in prices if p is not None and float(p) > 0]


def _ret_bin(close: list[float], i: int, lookback: int = 5) -> int:
    if i < lookback:
        return _N_RET_BINS // 2
    ret = close[i] / close[i - lookback] - 1.0
    # ±4% band → bins 0..4
    scaled = (ret + 0.04) / 0.08
    return max(0, min(_N_RET_BINS - 1, int(scaled * _N_RET_BINS)))


def _state_key(ret_bin: int, position: int) -> str:
    return f"{ret_bin},{position}"


def _empty_q() -> dict[str, list[float]]:
    return {}


def _q_row(q: dict[str, list[float]], key: str) -> list[float]:
    row = q.get(key)
    if row is None or len(row) != _ACTIONS:
        row = [0.0, 0.0, 0.0]
        q[key] = row
    return row


def train_and_save(
    prices: Sequence[float],
    *,
    symbol: str = "_default",
    episodes: int = 24,
    seed: int = 7,
) -> dict[str, Any]:
    close = _closes(prices)
    if len(close) < 32:
        return {"ok": False, "error": "need_at_least_32_closes", "symbol": symbol}

    try:
        from app.services.trading_engines.runtime.finrl_ppo import train_ppo

        ppo = train_ppo(close, episodes=min(int(episodes), 12), seed=seed)
        payload = {
            "algo": "ppo",
            "symbol": _safe_symbol(symbol),
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "bars": len(close),
            "episodes": min(int(episodes), 12),
            "actor": ppo["actor"],
            "critic": ppo["critic"],
        }
        path = model_path(symbol)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
        return {
            "ok": True,
            "mode": "trained_ppo",
            "symbol": payload["symbol"],
            "path": str(path),
            "bars": len(close),
            "episodes": payload["episodes"],
            "license": "PPO algorithm (FinRL family, MIT). ElegantRL not vendored.",
        }
    except Exception:
        pass

    episodes = max(4, min(int(episodes), 80))
    rng = random.Random(seed)
    q: dict[str, list[float]] = _empty_q()
    alpha = 0.15
    gamma = 0.92
    eps = 0.25

    for _ in range(episodes):
        pos = 0
        for i in range(5, len(close) - 1):
            key = _state_key(_ret_bin(close, i), pos)
            row = _q_row(q, key)
            action = rng.randrange(_ACTIONS) if rng.random() < eps else int(max(range(_ACTIONS), key=row.__getitem__))
            nxt_pos = action
            ret = close[i + 1] / close[i] - 1.0
            reward = nxt_pos_sign(nxt_pos) * ret - _FEE * abs(nxt_pos - pos)
            nkey = _state_key(_ret_bin(close, i + 1), nxt_pos)
            nrow = _q_row(q, nkey)
            target = reward + gamma * max(nrow)
            row[action] += alpha * (target - row[action])
            pos = nxt_pos
        eps = max(0.05, eps * 0.94)

    greedy_ret = _greedy_equity_return(close, q)
    payload = {
        "algo": "q_learning",
        "symbol": _safe_symbol(symbol),
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "bars": len(close),
        "episodes": episodes,
        "train_greedy_return": greedy_ret,
        "q": q,
    }
    path = model_path(symbol)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return {
        "ok": True,
        "mode": "trained_q_learning",
        "symbol": payload["symbol"],
        "path": str(path),
        "bars": len(close),
        "episodes": episodes,
        "train_greedy_return": greedy_ret,
    }


def nxt_pos_sign(action: int) -> int:
    if action == 1:
        return 1
    if action == 2:
        return -1
    return 0


def load_policy(symbol: str) -> dict[str, Any] | None:
    for name in (symbol, "_default"):
        path = model_path(name)
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if data.get("algo") == "ppo" and isinstance(data.get("actor"), dict):
            return data
        if isinstance(data.get("q"), dict):
            return data
    return None


def infer_direction(prices: Sequence[float], policy: dict[str, Any]) -> tuple[int, float]:
    if policy.get("algo") == "ppo" and isinstance(policy.get("actor"), dict):
        from app.services.trading_engines.runtime.finrl_ppo import infer_ppo

        return infer_ppo(prices, policy["actor"])
    close = _closes(prices)
    if len(close) < 8:
        return 0, 0.0
    q = policy.get("q") or {}
    key = _state_key(_ret_bin(close, len(close) - 1), 0)
    row = q.get(key) or [0.0, 0.0, 0.0]
    if len(row) != _ACTIONS:
        row = [0.0, 0.0, 0.0]
    action = int(max(range(_ACTIONS), key=lambda a: float(row[a])))
    strength = float(row[action]) - float(sum(row) / _ACTIONS)
    return nxt_pos_sign(action), strength


def _greedy_equity_return(close: list[float], q: dict[str, list[float]]) -> float:
    pos = 0
    equity = 1.0
    for i in range(5, len(close) - 1):
        key = _state_key(_ret_bin(close, i), pos)
        row = q.get(key) or [0.0, 0.0, 0.0]
        action = int(max(range(_ACTIONS), key=lambda a: float(row[a]) if a < len(row) else 0.0))
        ret = close[i + 1] / close[i] - 1.0
        equity *= 1.0 + nxt_pos_sign(action) * ret - _FEE * abs(action - pos)
        pos = action
    return float(equity - 1.0)
