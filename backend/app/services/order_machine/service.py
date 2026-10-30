"""Order states, paper fills, and guards. Does not call a broker.

States: created → sent → accepted → partial → filled, or rejected / cancelled.
Live mode is refused while qa_act_live is off. Margin and contract specs that
are not supplied by the caller stay «нет данных»; this module does not invent them.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.services.qa.feature_flags import is_enabled
from app.services.venue_adapters.key_check import inspect_key_permissions

MODEL_VERSION = "order_machine.v1"
_MISSING = "нет данных"
_NEXT = {
    "created": {"sent", "rejected", "cancelled"},
    "sent": {"accepted", "rejected", "cancelled"},
    "accepted": {"partial", "filled", "rejected", "cancelled"},
    "partial": {"partial", "filled", "rejected", "cancelled"},
}
_OPEN = {"created", "sent", "accepted", "partial"}
_AUTO = {"auto", "bot"}
_CONFIG = Path(__file__).with_name("config.json")

_orders: dict[str, dict[str, Any]] = {}
_halt_users: set[str] = set()
_halt_global = False
_reconcile_users: set[str] = set()
_relaxed: set[str] = set()
_limit_journal: list[dict[str, str]] = []
_events: list[dict[str, Any]] = []


def reset() -> None:
    """Clear in-memory machine state. Does not clear the portfolio book."""
    global _halt_global
    _orders.clear()
    _halt_users.clear()
    _reconcile_users.clear()
    _relaxed.clear()
    _limit_journal.clear()
    _events.clear()
    _halt_global = False


def _now() -> datetime:
    return datetime.now(UTC)


def _limits() -> dict[str, Any]:
    return json.loads(_CONFIG.read_text(encoding="utf-8"))


def _step(order: dict[str, Any], status: str, reason: str | None = None) -> None:
    current = str(order["status"])
    if status not in _NEXT.get(current, set()):
        raise ValueError(f"illegal transition {current} -> {status}")
    order["status"] = status
    order["transitions"].append({"from": current, "to": status, "at": _now().isoformat(), "reason": reason})
    if reason:
        order["reason"] = reason


def margin_view(
    *,
    instrument_kind: str,
    broker_margin: str | None = None,
    broker_leverage: str | None = None,
    broker_liquidation: str | None = None,
    holding_cost: str | None = None,
) -> dict[str, str]:
    """Show broker-supplied figures only. Anything else is «нет данных»."""
    kind = instrument_kind or _MISSING
    return {
        "instrument_kind": kind,
        "margin": broker_margin if broker_margin not in (None, "") else _MISSING,
        "leverage": broker_leverage if broker_leverage not in (None, "") else _MISSING,
        "liquidation": broker_liquidation if broker_liquidation not in (None, "") else _MISSING,
        "holding_cost": holding_cost if holding_cost not in (None, "") else _MISSING,
        "qualified_access": _MISSING,
        "underlying_risk": _MISSING if kind in {"perpetual", "future"} else "справочник",
    }


def venue_order_adapter(venue: str) -> dict[str, str]:
    """Finam has no order adapter in this repo. Tinkoff is not called while live is off."""
    name = venue.strip().lower()
    if name == "finam":
        return {"venue": "finam", "status": _MISSING, "reason": "адаптер заявок Финам в репозитории не найден"}
    if name in {"tinkoff", "tbank"}:
        return {"venue": name, "status": "off", "reason": "qa_act_live выключен, заявка брокеру не отправляется"}
    return {"venue": name or _MISSING, "status": _MISSING, "reason": _MISSING}


def moex_crypto_adapter() -> dict[str, str]:
    if not is_enabled("qa_moex_crypto"):
        return {"status": "off", "specs": _MISSING}
    return {"status": _MISSING, "specs": _MISSING}


def tokenized_form(ticker: str) -> dict[str, str]:
    """Link a known tokenized ticker to its asset. Execution right is not invented."""
    from app.services.catalog.resolve import resolve

    try:
        hit = resolve(ticker)
    except (KeyError, ValueError):
        return {"ticker": ticker, "asset_id": _MISSING, "execution": _MISSING}
    if hit.instrument_kind != "tokenized_equity":
        return {"ticker": ticker, "asset_id": _MISSING, "execution": _MISSING}
    return {"ticker": hit.symbol, "asset_id": hit.asset_id, "execution": _MISSING}


def automatic_blocked(user_id: str | None = None) -> bool:
    if not is_enabled("qa_order_machine"):
        return False
    return _halt_global or bool(user_id and (user_id in _halt_users or user_id in _reconcile_users))


def halt(*, actor: str, user_id: str | None = None) -> dict[str, Any]:
    """Stop automatic orders. Admin with no user id stops every account."""
    global _halt_global
    if not is_enabled("qa_order_machine"):
        return {"status": "off", "cancelled": []}
    if actor == "admin" and user_id is None:
        _halt_global = True
        scope = "global"
    elif user_id:
        _halt_users.add(user_id)
        scope = user_id
    else:
        raise ValueError("user id required")
    cancelled: list[str] = []
    for order in _orders.values():
        if order["status"] not in _OPEN:
            continue
        if order.get("actor") not in _AUTO:
            continue
        if scope != "global" and order["user_id"] != scope:
            continue
        _step(order, "cancelled", "halt")
        cancelled.append(order["client_order_id"])
    _events.append({"name": "halt", "scope": scope, "cancelled": list(cancelled)})
    return {"status": "halt", "scope": scope, "cancelled": cancelled}


def check_live_limits(*, user_id: str, notional: Decimal, now: datetime | None = None) -> str | None:
    """Product caps for live attempts. Not a broker fee schedule."""
    if user_id in _relaxed:
        return None
    limits = _limits()
    if notional > Decimal(str(limits["max_order_notional"])):
        return "номинал выше защитного лимита"
    stamp = now or _now()
    day = stamp.date()
    turnover = Decimal(0)
    recent = 0
    for order in _orders.values():
        if order["user_id"] != user_id or order.get("mode") != "live":
            continue
        opened = datetime.fromisoformat(order["opened_at"])
        if opened.date() == day and order["status"] in {"sent", "accepted", "partial", "filled"}:
            turnover += Decimal(str(order.get("notional") or "0"))
        if opened >= stamp - timedelta(minutes=1):
            recent += 1
    if turnover + notional > Decimal(str(limits["max_daily_turnover"])):
        return "дневной оборот выше защитного лимита"
    if recent >= int(limits["max_orders_per_minute"]):
        return "число заявок в минуту выше защитного лимита"
    return None


def relax_live_limits(*, user_id: str, confirm: bool) -> dict[str, str]:
    if not confirm:
        return {"status": "не изменено", "user_id": user_id}
    _relaxed.add(user_id)
    _limit_journal.append({"user_id": user_id, "at": _now().isoformat(), "action": "relax_live_limits"})
    return {"status": "снято", "user_id": user_id}


def reconcile(*, user_id: str, broker_orders: list[dict[str, str]] | None) -> dict[str, Any]:
    """Compare local open orders with a broker snapshot the caller already has."""
    if broker_orders is None:
        _reconcile_users.add(user_id)
        event = {"name": "reconcile", "user_id": user_id, "status": _MISSING}
        _events.append(event)
        return {"status": _MISSING, "automatic_blocked": True, "mismatches": []}
    local = {
        row["client_order_id"]: str(row.get("filled_qty") or "0")
        for row in _orders.values()
        if row["user_id"] == user_id and row["status"] in _OPEN | {"filled"}
    }
    remote = {row["client_order_id"]: str(row.get("filled_qty") or "0") for row in broker_orders}
    mismatches = sorted(key for key in set(local) | set(remote) if local.get(key) != remote.get(key))
    if mismatches:
        _reconcile_users.add(user_id)
        status = "расхождение"
    else:
        _reconcile_users.discard(user_id)
        status = "совпало"
    _events.append({"name": "reconcile", "user_id": user_id, "status": status, "mismatches": mismatches})
    return {"status": status, "automatic_blocked": bool(mismatches), "mismatches": mismatches}


def submit_order(
    *,
    user_id: str,
    client_order_id: str,
    ticker: str,
    side: str,
    qty: str,
    ccy: str,
    price: str | None = None,
    order_type: str = "limit",
    mode: str = "paper",
    actor: str = "human",
    confirmed: bool = False,
    instrument_kind: str = "equity",
    maneuver_key: str | None = None,
    scopes: list[str] | None = None,
    broker_margin: str | None = None,
    broker_leverage: str | None = None,
    broker_liquidation: str | None = None,
    holding_cost: str | None = None,
    venue: str = "paper",
) -> dict[str, Any]:
    if not is_enabled("qa_order_machine"):
        return {"status": "off", "client_order_id": client_order_id, "model_version": MODEL_VERSION}
    if client_order_id in _orders:
        return dict(_orders[client_order_id])
    if scopes is not None:
        inspect_key_permissions(venue, scopes)
    facts = margin_view(
        instrument_kind=instrument_kind,
        broker_margin=broker_margin,
        broker_leverage=broker_leverage,
        broker_liquidation=broker_liquidation,
        holding_cost=holding_cost,
    )
    order: dict[str, Any] = {
        "client_order_id": client_order_id,
        "user_id": user_id,
        "ticker": ticker.upper(),
        "side": side,
        "qty": str(Decimal(str(qty))),
        "filled_qty": "0",
        "price": price,
        "ccy": ccy,
        "order_type": order_type,
        "mode": mode,
        "actor": actor,
        "venue": venue,
        "instrument_kind": instrument_kind,
        "margin": facts,
        "status": "created",
        "transitions": [],
        "opened_at": _now().isoformat(),
        "model_version": MODEL_VERSION,
        "maneuver_key": maneuver_key,
        "reason": None,
        "notional": "0",
    }
    _orders[client_order_id] = order
    if not ccy or price in (None, ""):
        _step(order, "rejected", _MISSING)
        return dict(order)
    notional = abs(Decimal(str(qty)) * Decimal(str(price)))
    order["notional"] = format(notional, "f")
    if mode == "live":
        if not is_enabled("qa_act_live"):
            _step(order, "rejected", "qa_act_live выключен")
            return dict(order)
        limit_reason = check_live_limits(user_id=user_id, notional=notional)
        if limit_reason:
            _step(order, "rejected", limit_reason)
            return dict(order)
        adapter = venue_order_adapter(venue)
        _step(order, "rejected", adapter["reason"])
        return dict(order)
    if mode != "paper":
        _step(order, "rejected", _MISSING)
        return dict(order)
    if automatic_blocked(user_id) and actor in _AUTO:
        _step(order, "rejected", "halt")
        return dict(order)
    leveraged = instrument_kind in {"perpetual", "future"} or broker_leverage not in (None, "", "1")
    if actor in _AUTO and leveraged and facts["margin"] == _MISSING:
        _step(order, "rejected", _MISSING)
        return dict(order)
    from app.services.pretrade.policy import evaluate

    gate = evaluate(
        kind="bot" if actor in _AUTO else "manual_order",
        actor="auto" if actor in _AUTO else "human",
        user_id=user_id,
        ticker=ticker,
        qty=float(qty),
        price=float(price),
        mode="paper",
        confirmed=confirmed,
    )
    codes = {reason.code for reason in gate.reasons}
    if "instrument_unavailable" in codes or gate.verdict == "block" or (gate.verdict == "warn" and not confirmed):
        _step(order, "rejected", gate.reasons[0].code if gate.reasons else _MISSING)
        order["gate"] = gate.verdict
        return dict(order)
    _step(order, "sent", None)
    _step(order, "accepted", None)
    if order_type == "stop":
        return dict(order)
    _fill(order, Decimal(str(qty)), maneuver_key)
    return dict(order)


def add_fill(*, user_id: str, client_order_id: str, qty: str) -> dict[str, Any]:
    """Move an accepted or partial paper order forward. Same id does not duplicate a fill."""
    order = _orders.get(client_order_id)
    if order is None or order["user_id"] != user_id:
        raise KeyError(client_order_id)
    if order["status"] not in {"accepted", "partial"}:
        return dict(order)
    _fill(order, Decimal(str(qty)), order.get("maneuver_key"))
    return dict(order)


def _fill(order: dict[str, Any], qty: Decimal, maneuver_key: str | None) -> None:
    from app.services.portfolio_book.service import ensure_account, record_transaction

    already = Decimal(str(order.get("filled_qty") or "0"))
    target = Decimal(str(order["qty"]))
    take = qty if already + qty <= target else target - already
    if take <= 0:
        return
    count = int(order.get("fill_count") or 0) + 1
    order["fill_count"] = count
    external_id = maneuver_key if maneuver_key and count == 1 else f"{order['client_order_id']}:f{count}"
    price = Decimal(str(order["price"]))
    signed = -abs(take) if str(order["side"]).lower() == "sell" else abs(take)
    account_id = f"paper-act:{order['user_id']}"
    ensure_account(account_id=account_id, user_id=order["user_id"], venue="act", mode="paper", source="order_machine")
    record_transaction(
        account_id=account_id,
        user_id=order["user_id"],
        mode="paper",
        venue="act",
        external_id=external_id,
        kind="trade",
        instrument_id=order["ticker"],
        ticker=order["ticker"],
        qty=str(signed),
        amount=str(abs(take) * price),
        ccy=order["ccy"],
        event_time=_now(),
    )
    filled = already + take
    order["filled_qty"] = format(filled, "f")
    if filled < target:
        _step(order, "partial", None)
    else:
        _step(order, "filled", None)


def get_order(client_order_id: str) -> dict[str, Any] | None:
    row = _orders.get(client_order_id)
    return dict(row) if row else None
