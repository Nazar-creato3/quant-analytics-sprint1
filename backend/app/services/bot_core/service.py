"""Paper bots, a composer handoff, and backtest honesty checks.

Live is refused. Fees stay «нет данных» until config has them.
Deflated Sharpe and CSCV follow Bailey and López de Prado; short samples
stay «нет данных».
"""
from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from decimal import Decimal
from itertools import combinations
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.services.event_bus.bus import publish_event
from app.services.qa.feature_flags import is_enabled

MODEL_VERSION = "bot_core.v1"
_MISSING = "нет данных"
_REGIMES = {"trend_up", "trend_down", "range", "high_vol", "low_vol"}
_CONFIG = Path(__file__).with_name("config.json")

_bots: dict[str, dict[str, Any]] = {}
_events: list[dict[str, str]] = []


def reset() -> None:
    _bots.clear()
    _events.clear()


def _cfg() -> dict[str, Any]:
    return json.loads(_CONFIG.read_text(encoding="utf-8"))


def _cost(name: str) -> str:
    raw = _cfg().get(name)
    if raw in (None, ""):
        return _MISSING
    return str(raw)


def list_bots(user_id: str) -> list[dict[str, Any]]:
    return [dict(row) for row in _bots.values() if row["user_id"] == user_id]


def request_live(bot_id: str) -> dict[str, str]:
    row = _bots.get(bot_id)
    if row is None:
        raise KeyError(bot_id)
    needed = int(_cfg()["paper_days_before_live"])
    if not is_enabled("qa_act_live"):
        row["live"] = False
        # GA16-309: user-facing reason must not name the feature flag.
        return {"status": "rejected", "reason": "живая отправка недоступна", "paper_days": str(needed)}
    return {"status": "rejected", "reason": "живая отправка не подключена", "paper_days": str(needed)}


def open_paper(
    *,
    user_id: str,
    ticker: str,
    qty: str,
    price: str | None,
    ccy: str,
    side: str = "buy",
    kind: str = "spot",
    stop: str | None = None,
    source: str = "bot",
) -> dict[str, Any]:
    if not is_enabled("qa_bot_core"):
        return {"status": "off"}
    if price in (None, ""):
        return {"status": "rejected", "reason": _MISSING}
    if kind in {"future", "perpetual"}:
        return {"status": "rejected", "reason": _MISSING, "margin": _MISSING, "liquidation": _MISSING}
    bot_id = uuid4().hex[:12]
    row: dict[str, Any] = {
        "id": bot_id,
        "user_id": user_id,
        "ticker": ticker.upper(),
        "qty": str(Decimal(str(qty))),
        "price": str(price),
        "ccy": ccy,
        "side": side,
        "kind": kind,
        "stop": stop,
        "source": source,
        "status": "paper",
        "live": False,
        "commission_bps": _cost("commission_bps"),
        "slippage_bps": _cost("slippage_bps"),
        "model_version": MODEL_VERSION,
    }
    from app.services.pretrade.policy import evaluate

    gate = evaluate(
        kind="bot",
        actor="auto",
        user_id=user_id,
        ticker=ticker,
        qty=float(qty),
        price=float(price),
        mode="paper",
        confirmed=False,
    )
    if gate.verdict == "block":
        row["status"] = "rejected"
        row["reason"] = gate.reasons[0].code if gate.reasons else _MISSING
        _bots[bot_id] = row
        return dict(row)
    from app.services.portfolio_book.service import record_bot_trade

    record_bot_trade(
        user_id=user_id,
        ticker=row["ticker"],
        qty=row["qty"],
        amount=str(abs(Decimal(row["qty"]) * Decimal(row["price"]))),
        ccy=ccy,
        side=side,
        external_id=f"bot:{bot_id}",
        event_time=datetime.now(UTC),
    )
    _bots[bot_id] = row
    _emit("bot.opened", bot_id)
    return dict(row)


def pause_if_breached(*, bot_id: str, mark: str | None) -> dict[str, Any]:
    row = _bots.get(bot_id)
    if row is None:
        raise KeyError(bot_id)
    if mark in (None, "") or row.get("stop") in (None, ""):
        row["protection"] = _MISSING
        return dict(row)
    mark_n = Decimal(str(mark))
    stop_n = Decimal(str(row["stop"]))
    breached = mark_n <= stop_n if row["side"] == "buy" else mark_n >= stop_n
    if not breached:
        return dict(row)
    row["status"] = "paused"
    _emit("bot.paused", bot_id)
    return dict(row)


def create_from_composer(
    *,
    user_id: str,
    ticker: str,
    regime: str,
    strategy: str,
    qty: str,
    price: str | None,
    ccy: str,
) -> dict[str, Any]:
    if regime not in _REGIMES:
        return {"status": _MISSING, "reason": _MISSING}
    opened = open_paper(
        user_id=user_id,
        ticker=ticker,
        qty=qty,
        price=price,
        ccy=ccy,
        source="composer",
    )
    if opened.get("id"):
        _bots[opened["id"]]["regime"] = regime
        _bots[opened["id"]]["strategy"] = strategy
        opened = dict(_bots[opened["id"]])
    return opened


def leaks(signal_at: datetime, trade_at: datetime) -> bool:
    """True when the trade is timestamped before the signal that is said to cause it."""
    return trade_at < signal_at


def deflated_sharpe(sharpe: float, trials: int, observations: int, skew: float = 0.0, kurt: float = 3.0) -> str:
    """Bailey & López de Prado, The Deflated Sharpe Ratio (2014). Missing inputs stay unset."""
    if trials < 2 or observations < 3:
        return _MISSING
    sr0 = math.sqrt(2.0 * math.log(trials)) * (1.0 - math.e / (2.0 * math.log(trials)))
    denom = math.sqrt(max(1e-12, 1.0 - skew * sharpe + ((kurt - 1.0) / 4.0) * sharpe * sharpe))
    z = (sharpe - sr0) * math.sqrt(observations - 1) / denom
    cdf = 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
    return format(cdf, "f")


def cscv_pbo(matrix: list[list[float]]) -> str:
    """Probability of backtest overfitting via CSCV. Columns are strategy variants."""
    if len(matrix) < 4 or not matrix[0] or len(matrix[0]) < 2:
        return _MISSING
    rows = len(matrix)
    cols = len(matrix[0])
    splits = rows // 2
    worse = 0
    total = 0
    for chosen in combinations(range(rows), splits):
        hold = [i for i in range(rows) if i not in set(chosen)]
        if len(hold) != splits:
            continue
        is_means = [_mean([matrix[i][c] for i in chosen]) for c in range(cols)]
        best = max(range(cols), key=lambda c: is_means[c])
        oos = sorted(_mean([matrix[i][c] for i in hold]) for c in range(cols))
        rank = oos.index(_mean([matrix[i][best] for i in hold]))
        if rank < len(oos) / 2:
            worse += 1
        total += 1
        if total >= 16:
            break
    if total == 0:
        return _MISSING
    return format(Decimal(worse) / Decimal(total), "f")


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _emit(name: str, bot_id: str) -> None:
    _events.append({"name": name, "bot_id": bot_id})
    try:
        publish_event(name, {"bot_id": bot_id})
    except Exception:  # noqa: BLE001 — the bus must not drop the stored paper state
        return


def event_names() -> list[str]:
    return [row["name"] for row in _events]
