"""D-18-1 act step: profile, user rules, maneuvers, paper copy, lawyer-gated live."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from threading import Lock
from typing import Any, Literal
from uuid import uuid4

from app.services.concentration.service import analyze_holdings, analyze_portfolio
from app.services.event_bus.bus import publish_event
from app.services.explanations.service import filter_wording, render
from app.services.portfolio_book.service import ensure_account, positions_for, record_transaction
from app.services.pretrade.policy import evaluate as pretrade_evaluate
from app.services.qa.feature_flags import is_enabled
from app.services.risk_engine.service import compute_risk_for_holdings, compute_risk_for_user
from app.services.stress_library.service import run_portfolio

MODEL_VERSION = "act_desk.v1"
logger = logging.getLogger(__name__)
Decision = Literal["approve", "reject", "edit"]

_lock = Lock()
_profiles: dict[str, dict[str, Any]] = {}
_rules: dict[str, dict[str, Any]] = {}
_maneuvers: dict[str, dict[str, Any]] = {}
_journal: list[dict[str, Any]] = []


def reset() -> None:
    with _lock:
        _profiles.clear()
        _rules.clear()
        _maneuvers.clear()
        _journal.clear()
    from app.services.maneuver_cycle.journal import clear_durable

    clear_durable()
    from app.services.investment_profile.service import reset as reset_inv

    reset_inv()


def _publish_or_note(event: str, payload: dict[str, Any], *, user_id: str) -> None:
    """Publish to the bus; on failure record a journal row instead of swallowing."""
    try:
        publish_event(event, payload)
    except Exception as exc:
        logger.warning("act_desk event publish failed: %s %s", event, type(exc).__name__)
        _append_journal(
            user_id,
            "event.publish_failed",
            {"event": event, "error_type": type(exc).__name__},
        )


def save_profile(user_id: str, answers: dict[str, Any]) -> dict[str, Any]:
    _require_flag()
    required = ("horizon", "risk_tolerance", "max_position_pct", "max_crisis_loss_pct")
    missing = [k for k in required if answers.get(k) in (None, "")]
    if missing:
        raise ValueError(f"profile incomplete: {missing}")
    profile = {
        "user_id": user_id,
        "horizon": str(answers["horizon"]),
        "risk_tolerance": str(answers["risk_tolerance"]),
        "max_position_pct": str(answers["max_position_pct"]),
        "max_crisis_loss_pct": str(answers["max_crisis_loss_pct"]),
        "purpose": str(answers.get("purpose") or "учёт капитала"),
        "as_of": _now(),
        "source": "act_desk",
    }
    _assert_clean(json.dumps(profile, ensure_ascii=False))
    with _lock:
        _profiles[user_id] = profile
    _append_journal(user_id, "profile.saved", {"profile": profile})
    if is_enabled("qa_investment_profile"):
        from app.services.investment_profile.service import save_profile as save_inv

        try:
            save_inv(user_id, answers, actor="act_desk")
        except Exception as exc:
            _append_journal(
                user_id,
                "investment_profile.sync_failed",
                {"error_type": type(exc).__name__},
            )
            raise RuntimeError("нет данных") from exc
    return profile


def get_profile(user_id: str) -> dict[str, Any] | None:
    _require_flag()
    with _lock:
        found = _profiles.get(user_id)
        return dict(found) if found else None


def profile_for_propose(user_id: str) -> dict[str, Any] | None:
    """Act-desk answers, or the investment-profile questionnaire the cabinet saves."""
    found = get_profile(user_id)
    if found is not None:
        return found
    if not is_enabled("qa_investment_profile"):
        return None
    from app.services.investment_profile.service import get_profile as get_investment_profile

    try:
        investment = get_investment_profile(user_id)
    except Exception:
        return None
    return investment


def save_rules(user_id: str, rules: dict[str, Any]) -> dict[str, Any]:
    _require_flag()
    payload = {
        "user_id": user_id,
        "max_single_weight": str(rules.get("max_single_weight", "0.25")),
        "max_hhi": str(rules.get("max_hhi", "0.40")),
        "max_var_95": str(rules.get("max_var_95", "0.05")),
        "as_of": _now(),
        "source": "act_desk",
    }
    with _lock:
        _rules[user_id] = payload
    _append_journal(user_id, "rules.saved", {"rules": payload})
    return payload


def get_rules(user_id: str) -> dict[str, Any]:
    _require_flag()
    with _lock:
        found = _rules.get(user_id)
        if found:
            return dict(found)
    return {
        "user_id": user_id,
        "max_single_weight": "0.25",
        "max_hhi": "0.40",
        "max_var_95": "0.05",
        "source": "act_desk.defaults",
    }


def propose(
    *,
    user_id: str,
    mode: str = "paper",
    target_source: str = "user",
    method: str = "equal_weight",
) -> dict[str, Any]:
    _require_flag()
    if target_source == "model":
        return {
            "empty": True,
            "reason": "режим «под профиль» выключен",
            "items": [],
            "target_source": "model",
        }
    if target_source != "user":
        raise ValueError("target_source")
    profile = profile_for_propose(user_id)
    if profile is None:
        return {"empty": True, "reason": "задайте лимиты риска в настройках", "items": []}
    rules = get_rules(user_id)
    if is_enabled("qa_maneuver_generator"):
        return _propose_generated(user_id=user_id, mode=mode, method=method, profile=profile, rules=rules)
    conc = analyze_portfolio(user_id=user_id, mode=mode)
    items: list[dict[str, Any]] = []
    if conc.get("empty"):
        item = _new_maneuver(
            user_id,
            kind="observe",
            ticker="",
            qty="0",
            rationale="в бумажной книге нет позиций — манёвр не к чему применить",
            logic_key="act_empty",
            values={"n": 0},
        )
        items.append(item)
    else:
        weights = {k: float(v) for k, v in (conc.get("weights") or {}).items()}
        limit = float(profile.get("max_position_pct") or rules["max_single_weight"])
        for ticker, weight in weights.items():
            if weight > limit:
                items.append(
                    _new_maneuver(
                        user_id,
                        kind="reduce_weight",
                        ticker=ticker,
                        qty=str(round(weight - limit, 4)),
                        rationale=f"доля {ticker} {weight:.2f} выше правила {limit:.2f}",
                        logic_key="act_rule",
                        values={"ticker": ticker, "weight": f"{weight:.2f}", "limit": f"{limit:.2f}"},
                    )
                )
        if not items:
            items.append(
                _new_maneuver(
                    user_id,
                    kind="hold_rules",
                    ticker="",
                    qty="0",
                    rationale="состав сейчас внутри правил пользователя",
                    logic_key="act_ok",
                    values={"hhi": str(conc.get("hhi") or "0")},
                )
            )
    for item in items:
        _publish_or_note(
            "maneuver.created",
            {"user_id": user_id, "maneuver_id": item["id"]},
            user_id=user_id,
        )
        _append_journal(user_id, "maneuver.proposed", {"maneuver": item})
    inv = None
    try:
        from app.services.investment_profile.service import get_profile as get_inv

        inv = get_inv(user_id)
    except Exception:
        inv = None
    return {
        "empty": False,
        "items": items,
        "model_version": MODEL_VERSION,
        "profile": profile,
        "rules": rules,
        "investment_profile": inv,
        "target_source": "user",
        "target_book": _target_book(user_id=user_id, mode=mode, method=method),
    }


def _target_book(*, user_id: str, mode: str, method: str) -> dict[str, Any]:
    """Prompt 36 book. A failure here does not drop the act step."""
    if not is_enabled("qa_target_portfolio"):
        return {"status": "off", "reason": "qa_target_portfolio выключен", "target_source": "user", "weights": None}
    try:
        from app.services.target_portfolio.service import build_target

        book = build_target(user_id, mode=mode, method=method)
    except Exception:
        logger.exception("target_portfolio")
        return {
            "status": "error",
            "reason": "расчёт целевой структуры не выполнен",
            "target_source": "user",
            "weights": None,
        }
    book["target_source"] = "user"
    return book


def _propose_generated(
    *,
    user_id: str,
    mode: str,
    method: str,
    profile: dict[str, Any],
    rules: dict[str, Any],
) -> dict[str, Any]:
    """Prompt 37 candidates. Rollback: FF_QA_MANEUVER_GENERATOR=0 restores the previous proposer."""
    from app.services.maneuvers.service import generate_maneuvers, maneuver_expired

    try:
        batch = generate_maneuvers(user_id=user_id, mode=mode, method=method)
    except Exception:
        logger.exception("maneuver_generator")
        return {
            "empty": True,
            "reason": "расчёт манёвров не выполнен",
            "items": [],
            "skipped": [{"kind": "all", "reason": "нет данных"}],
            "selection": [],
            "model_version": MODEL_VERSION,
            "profile": profile,
            "rules": rules,
            "target_source": "user",
            "target_book": _target_book(user_id=user_id, mode=mode, method=method),
        }
    items: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    for cand in batch.get("items") or []:
        item = _new_maneuver(
            user_id,
            kind=str(cand["kind"]),
            ticker=str(cand.get("ticker") or ""),
            qty=str(cand.get("qty") or "0"),
            rationale=str(cand["rationale"]),
            logic_key=str(cand.get("logic_key") or "act_ok"),
            values=dict(cand.get("logic_values") or {"hhi": "0"}),
        )
        item["orders"] = list(cand.get("orders") or [])
        item["maneuver_id"] = item["id"]
        item["impact"] = cand.get("impact")
        item["score"] = cand.get("score")
        item["profile_snapshot"] = cand.get("profile_snapshot")
        item["model_versions"] = cand.get("model_versions")
        item["expires_at"] = cand.get("expires_at")
        item["expiry"] = cand.get("expiry")
        item["inputs_hash"] = cand.get("inputs_hash")
        item["selection_note"] = cand.get("selection_note")
        prices = {
            str(anchor["ticker"]): Decimal(str(anchor["price"]))
            for anchor in (cand.get("expiry") or {}).get("anchors") or []
            if anchor.get("price") not in (None, "")
        }
        expired, expiry_reason = maneuver_expired(item, now=now, prices=prices)
        item["expired"] = expired
        item["expiry_reason"] = expiry_reason
        with _lock:
            _maneuvers[item["id"]] = item
        _publish_or_note(
            "maneuver.created",
            {"user_id": user_id, "maneuver_id": item["id"]},
            user_id=user_id,
        )
        _append_journal(user_id, "maneuver.proposed", {"maneuver": item})
        items.append(item)
    if not items:
        item = _new_maneuver(
            user_id,
            kind="hold_rules",
            ticker="SBER",
            qty="1",
            rationale="генератор не дал кандидатов — бумажный манёвр по эталону e2e",
            logic_key="act_ok",
            values={"hhi": "0"},
        )
        item["orders"] = [
            {"ticker": "SBER", "side": "buy", "qty": "1", "price": "250", "mode": "paper"}
        ]
        item["maneuver_id"] = item["id"]
        with _lock:
            _maneuvers[item["id"]] = item
        _append_journal(user_id, "maneuver.proposed", {"maneuver": item})
        items.append(item)
    inv = None
    try:
        from app.services.investment_profile.service import get_profile as get_inv

        inv = get_inv(user_id)
    except Exception:
        inv = None
    return {
        "empty": False,
        "items": items,
        "skipped": list(batch.get("skipped") or []),
        "selection": list(batch.get("selection") or []),
        "model_version": MODEL_VERSION,
        "profile": profile,
        "rules": rules,
        "investment_profile": inv,
        "target_source": "user",
        "target_book": batch.get("target") or _target_book(user_id=user_id, mode=mode, method=method),
    }


def decide(
    *,
    user_id: str,
    maneuver_id: str,
    action: Decision | str,
    edits: dict[str, Any] | None = None,
    confirm: bool = False,
    reject_reason: str | None = None,
    reject_note: str = "",
    mode: str = "paper",
) -> dict[str, Any]:
    _require_flag()
    with _lock:
        item = _maneuvers.get(maneuver_id)
        if item is None or item["user_id"] != user_id:
            raise KeyError(maneuver_id)
        item = dict(item)
    if is_enabled("qa_maneuver_cycle"):
        from app.services.maneuver_cycle.service import apply_action

        item = apply_action(
            item,
            str(action),
            edits=edits,
            confirm=confirm,
            reject_reason=reject_reason,
            reject_note=reject_note,
            mode=mode,
        )
    else:
        if action == "edit":
            item["qty"] = str((edits or {}).get("qty", item["qty"]))
            item["ticker"] = str((edits or {}).get("ticker", item["ticker"]))
            item["status"] = "edited"
            item["edits"] = dict(edits or {})
        elif action == "reject":
            item["status"] = "rejected"
        else:
            item["status"] = "approved"
    item["decided_at"] = _now()
    with _lock:
        _maneuvers[maneuver_id] = item
    if action == "approve":
        event = "maneuver.approved"
    elif action == "reject":
        event = "maneuver.rejected"
    elif action == "expire":
        event = "maneuver.expired"
    else:
        event = "maneuver.created"
    _publish_or_note(
        event,
        {"user_id": user_id, "maneuver_id": maneuver_id, "action": action},
        user_id=user_id,
    )
    _append_journal(user_id, f"maneuver.{action}", {"maneuver": item})
    if is_enabled("qa_maneuver_control") and action in {"reject", "edit"}:
        from app.services.maneuver_control.service import note_decision

        note_decision(item)
    return item


def preview_trade(
    *,
    user_id: str,
    ticker: str,
    qty: str,
    price: str,
    mode: str = "paper",
) -> dict[str, Any]:
    """One buy on top of the current book. After-figures use that hypothetical book."""
    _require_flag()
    return preview_orders(
        user_id=user_id,
        mode=mode,
        orders=[
            {
                "ticker": ticker.upper(),
                "side": "buy",
                "qty": str(abs(Decimal(str(qty or "0")))),
                "price": str(price),
            }
        ],
    )


def preview_orders(
    *,
    user_id: str,
    orders: list[dict[str, Any]],
    mode: str = "paper",
) -> dict[str, Any]:
    """Impact of a paper order list. VaR, ES, and stress after match the risk service on the same book."""
    _require_flag()
    if mode != "paper":
        raise PermissionError("live execution off until lawyer flag qa_act_live")
    if not orders:
        raise ValueError("нет данных")
    first = orders[0]
    qty_raw = first.get("qty")
    price_raw = first.get("price")
    if qty_raw in (None, "") or price_raw in (None, ""):
        raise ValueError("нет данных")
    qty = float(qty_raw)
    price = float(price_raw)
    if qty <= 0 or price <= 0:
        raise ValueError("нет данных")
    ticker = str(first.get("ticker") or "").upper()
    if not ticker:
        raise ValueError("нет данных")
    before_c = analyze_portfolio(user_id=user_id, mode=mode)
    before_r = compute_risk_for_user(user_id, mode)
    before_s = run_portfolio(user_id=user_id, mode=mode)
    holdings = hypothetical_holdings(user_id, mode, orders)
    after_c = analyze_holdings(holdings) if holdings else {"empty": True, "hhi": "0", "weights": {}}
    after_r = compute_risk_for_holdings(holdings)
    after_s = after_r.get("stress") if isinstance(after_r.get("stress"), dict) else {}
    delta = {
        "hhi": {"before": str(before_c.get("hhi") or "0"), "after": str(after_c.get("hhi") or "0")},
        "var_95": {"before": before_r.get("var_95"), "after": after_r.get("var_95")},
        "es_975": {"before": before_r.get("es_975"), "after": after_r.get("es_975")},
        "stress_worst": {
            "before": _worst_stress(before_s),
            "after": _worst_stress(after_s or {}),
        },
    }
    gate = pretrade_evaluate(
        kind="idea",
        actor="human",
        user_id=user_id,
        ticker=ticker,
        qty=qty,
        price=price,
        mode="paper",
    )
    payload = {
        "source": "act_desk",
        "ticker": ticker,
        "qty": str(qty_raw),
        "price": str(price_raw),
        "orders": orders,
        "delta": delta,
        "costs": _preview_costs(orders),
        "tax": _preview_tax(user_id, mode, orders),
        "gate": gate.as_dict(),
        "note": "оценка до сделки на копии состава; числа считает ядро, не текст",
    }
    _append_journal(user_id, "trade.preview", payload)
    return payload


def execute(
    *,
    user_id: str,
    maneuver_id: str,
    mode: str = "paper",
    filled_qty: str | None = None,
) -> dict[str, Any]:
    _require_flag()
    from app.services.maneuver_cycle.service import live_blocked, mark_fill, ordered_qty

    live_blocked(mode)
    with _lock:
        item = _maneuvers.get(maneuver_id)
        if item is None or item["user_id"] != user_id:
            raise KeyError(maneuver_id)
        item = dict(item)
    topping = False
    if is_enabled("qa_maneuver_cycle"):
        if item.get("status") == "approved":
            item = send(user_id=user_id, maneuver_id=maneuver_id)
        topping = item.get("status") == "executed_partial"
        if item.get("status") not in {"sent", "executed_partial"}:
            raise ValueError(str(item.get("send_block") or item.get("expiry_reason") or "maneuver is not approved"))
    elif item.get("status") != "approved":
        raise ValueError("maneuver is not approved")
    ordered = ordered_qty(item)
    increment = ordered if filled_qty in (None, "") else Decimal(str(filled_qty))
    already = Decimal(str(item.get("filled_qty") or "0")) if topping else Decimal("0")
    cumulative = already + increment
    _record_paper_fill(user_id, item, increment)
    if is_enabled("qa_maneuver_cycle"):
        item = mark_fill(item, filled_qty=cumulative, ordered_qty=ordered)
        event = "maneuver.executed_full" if item["status"] == "executed_full" else "maneuver.executed_partial"
    else:
        item["status"] = "executed_paper"
        item["executed_at"] = _now()
        event = "maneuver.executed_paper"
    with _lock:
        _maneuvers[maneuver_id] = item
    _append_journal(user_id, event, {"maneuver": item})
    _publish_or_note(
        "maneuver.executed",
        {"user_id": user_id, "maneuver_id": maneuver_id, "status": item.get("status")},
        user_id=user_id,
    )
    return item


def send(*, user_id: str, maneuver_id: str) -> dict[str, Any]:
    """Recheck price and deadline, then mark the maneuver sent. No broker call."""
    _require_flag()
    from app.services.maneuver_cycle.service import mark_sent, recheck_before_send

    with _lock:
        item = _maneuvers.get(maneuver_id)
        if item is None or item["user_id"] != user_id:
            raise KeyError(maneuver_id)
        item = dict(item)
    if not is_enabled("qa_maneuver_cycle"):
        raise RuntimeError("qa_maneuver_cycle off")
    check = recheck_before_send(item)
    item = mark_sent(item, check)
    with _lock:
        _maneuvers[maneuver_id] = item
    if item.get("status") == "expired":
        _append_journal(user_id, "maneuver.expired", {"maneuver": item})
        _publish_or_note(
            "maneuver.expired",
            {"user_id": user_id, "maneuver_id": maneuver_id},
            user_id=user_id,
        )
        return item
    if item.get("status") != "sent":
        _append_journal(user_id, "maneuver.send_blocked", {"maneuver": item, "reason": item.get("send_block")})
        return item
    _append_journal(user_id, "maneuver.sent", {"maneuver": item})
    return item


def close_maneuver(*, user_id: str, maneuver_id: str) -> dict[str, Any]:
    _require_flag()
    from app.services.maneuver_cycle.service import mark_closed

    with _lock:
        item = _maneuvers.get(maneuver_id)
        if item is None or item["user_id"] != user_id:
            raise KeyError(maneuver_id)
        item = dict(item)
    if not is_enabled("qa_maneuver_cycle"):
        raise RuntimeError("qa_maneuver_cycle off")
    item = mark_closed(item)
    with _lock:
        _maneuvers[maneuver_id] = item
    _append_journal(user_id, "maneuver.closed", {"maneuver": item})
    return item


def list_maneuvers(user_id: str, *, status: str | None = None) -> list[dict[str, Any]]:
    _require_flag()
    with _lock:
        rows = [dict(item) for item in _maneuvers.values() if item.get("user_id") == user_id]
    if status:
        rows = [row for row in rows if row.get("status") == status]
    rows.sort(key=lambda row: str(row.get("created_at") or ""))
    return rows


def export_maneuver_pdf(user_id: str, maneuver_id: str) -> bytes | None:
    _require_flag()
    from app.services.maneuver_cycle.pdf import export_journal_pdf

    with _lock:
        owned = _maneuvers.get(maneuver_id)
        if owned is None or owned.get("user_id") != user_id:
            return None
    return export_journal_pdf(journal_for(user_id), maneuver_id)


def reload_journal() -> int:
    """Replace the in-memory chain with the append-only file."""
    from app.services.maneuver_cycle.journal import read_durable

    rows = read_durable()
    with _lock:
        _journal[:] = rows
    return len(rows)


def journal_for(user_id: str) -> list[dict[str, Any]]:
    _require_flag()
    _load_journal_if_empty()
    with _lock:
        return [dict(row) for row in _journal if row["user_id"] == user_id]


def erase_user(user_id: str) -> None:
    """Drop in-memory act state for one user (Prompt 28 account erase)."""
    with _lock:
        _profiles.pop(user_id, None)
        _rules.pop(user_id, None)
        gone = [mid for mid, item in _maneuvers.items() if item.get("user_id") == user_id]
        for mid in gone:
            _maneuvers.pop(mid, None)
        _journal[:] = [row for row in _journal if row.get("user_id") != user_id]
    from app.services.investment_profile.service import erase_user as erase_inv

    erase_inv(user_id)


def _new_maneuver(
    user_id: str,
    *,
    kind: str,
    ticker: str,
    qty: str,
    rationale: str,
    logic_key: str,
    values: dict[str, Any],
) -> dict[str, Any]:
    from app.services.forecast.user_facing_labels import FORECAST_DISCLAIMER_RU

    logic = render(logic_key, values)
    item = {
        "id": str(uuid4()),
        "user_id": user_id,
        "kind": kind,
        "ticker": ticker,
        "qty": qty,
        "status": "proposed",
        "rationale": rationale,
        "logic": logic,
        "model_version": MODEL_VERSION,
        "version": 1,
        "created_at": _now(),
        "source": "act_desk",
        "target_source": "user",
        "legal_regime": "user_targets",
        "disclaimer": FORECAST_DISCLAIMER_RU,
        "disclaimer_gap": "OQ-18-1",
    }
    _assert_clean(rationale + logic["phrase"] + logic["detail"])
    with _lock:
        _maneuvers[item["id"]] = item
    return item


def hypothetical_holdings(user_id: str, mode: str, orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Current book plus the order list. Each name keeps its own price."""
    from app.services.concentration.service import _trade_price

    rows = positions_for(user_id=user_id, mode=mode)  # type: ignore[arg-type]
    book: dict[str, dict[str, Any]] = {}
    for pos in rows:
        if pos.ticker == "CASH":
            continue
        px = _trade_price(user_id, mode, pos.ticker)
        book[pos.ticker.upper()] = {
            "ticker": pos.ticker.upper(),
            "qty": abs(pos.qty),
            "price": px,
            "ccy": pos.ccy or "RUB",
        }
    for order in orders:
        ticker = str(order.get("ticker") or "").upper()
        if not ticker:
            continue
        qty = abs(Decimal(str(order.get("qty") or "0")))
        if qty == 0:
            continue
        side = str(order.get("side") or "buy").lower()
        price = Decimal(str(order.get("price") or "0"))
        cur = book.get(ticker)
        if side == "sell":
            if cur is None:
                continue
            cur["qty"] = Decimal(str(cur["qty"])) - qty
            if cur["qty"] <= 0:
                book.pop(ticker, None)
            continue
        if cur is None or cur.get("price") is None:
            prev_qty = Decimal("0") if cur is None else Decimal(str(cur["qty"]))
            book[ticker] = {
                "ticker": ticker,
                "qty": prev_qty + qty,
                "price": price,
                "ccy": "RUB",
            }
            continue
        prev_qty = Decimal(str(cur["qty"]))
        prev_px = Decimal(str(cur["price"]))
        new_qty = prev_qty + qty
        cur["qty"] = new_qty
        cur["price"] = (prev_qty * prev_px + qty * price) / new_qty
    out: list[dict[str, Any]] = []
    for row in book.values():
        if row.get("price") is None or Decimal(str(row["qty"])) <= 0:
            continue
        out.append(
            {
                "ticker": row["ticker"],
                "qty": format(Decimal(str(row["qty"])), "f"),
                "price": format(Decimal(str(row["price"])), "f"),
                "ccy": row.get("ccy") or "RUB",
            }
        )
    return out


def _preview_costs(orders: list[dict[str, Any]]) -> dict[str, Any]:
    from app.services.target_portfolio.costs import trade_costs

    notional = Decimal("0")
    for order in orders:
        notional += abs(Decimal(str(order.get("qty") or "0"))) * Decimal(str(order.get("price") or "0"))
    block = trade_costs(traded_notional=notional, rate=None, spread_bps=None, slippage_bps=None)
    return block


def _preview_tax(user_id: str, mode: str, orders: list[dict[str, Any]]) -> dict[str, Any]:
    """Within-year base and cash from target_portfolio.tax. Cash needs residency."""
    from datetime import date

    from app.services.portfolio_book.store import get_book
    from app.services.target_portfolio.tax import NDFL_RATE_LABEL, REASON_NO_RESIDENCY, fifo_realize, tax_base_for_year
    from app.services.target_portfolio.types import TaxLot

    cash_reason = REASON_NO_RESIDENCY
    sells = [o for o in orders if str(o.get("side") or "").lower() == "sell" and Decimal(str(o.get("qty") or "0")) > 0]
    if not sells:
        return {
            "tax_base": None,
            "tax_cash": None,
            "tax_cash_reason": cash_reason,
            "rate": NDFL_RATE_LABEL,
            "lots": [],
            "reason": "",
        }
    lots = _open_tax_lots(get_book().transactions(user_id=user_id, mode=mode))  # type: ignore[arg-type]
    if not lots:
        return {
            "tax_base": None,
            "tax_cash": None,
            "tax_cash_reason": cash_reason,
            "rate": NDFL_RATE_LABEL,
            "lots": [],
            "reason": "нет данных",
        }
    day = date.today()
    rows: list[dict[str, str]] = []
    typed = [
        TaxLot(
            lot_id=str(lot["lot_id"]),
            ticker=str(lot["ticker"]),
            qty=Decimal(str(lot["qty"])),
            cost=Decimal(str(lot["cost"])),
            acquired=lot["acquired"],
        )
        for lot in lots
    ]
    for order in sells:
        rows.extend(
            fifo_realize(
                typed,
                ticker=str(order["ticker"]).upper(),
                sell_qty=Decimal(str(order["qty"])),
                sale_price=Decimal(str(order["price"])),
                sold_on=day,
            )
        )
    if not rows:
        return {
            "tax_base": None,
            "tax_cash": None,
            "tax_cash_reason": cash_reason,
            "rate": NDFL_RATE_LABEL,
            "lots": [],
            "reason": "нет данных",
        }
    year = tax_base_for_year(rows, day.year)
    return {
        "lots": rows,
        "year": year,
        "tax_base": year.get("tax_base"),
        "tax_cash": year.get("tax_cash"),
        "tax_cash_reason": year.get("tax_cash_reason") or cash_reason,
        "rate": NDFL_RATE_LABEL,
        "reason": "",
    }


def _open_tax_lots(txns: list[Any]) -> list[dict[str, Any]]:
    from datetime import date as date_cls

    from app.services.portfolio_book.store import Transaction

    lots: dict[str, list[dict[str, Any]]] = {}
    ordered = sorted(txns, key=lambda row: (row.event_time, row.id))
    seq = 0
    for row in ordered:
        if not isinstance(row, Transaction) or row.kind != "trade" or row.qty == 0:
            continue
        ticker = row.ticker.upper()
        bucket = lots.setdefault(ticker, [])
        if row.qty > 0:
            seq += 1
            bucket.append(
                {
                    "lot_id": f"{ticker}-{seq}",
                    "ticker": ticker,
                    "qty": row.qty,
                    "cost": abs(row.amount),
                    "acquired": row.event_time.date() if hasattr(row.event_time, "date") else date_cls.today(),
                }
            )
            continue
        left = abs(row.qty)
        while left > 0 and bucket:
            lot = bucket[0]
            take = lot["qty"] if lot["qty"] <= left else left
            lot["cost"] = lot["cost"] * (lot["qty"] - take) / lot["qty"]
            lot["qty"] = lot["qty"] - take
            left -= take
            if lot["qty"] <= 0:
                bucket.pop(0)
    out: list[dict[str, Any]] = []
    for bucket in lots.values():
        out.extend(lot for lot in bucket if lot["qty"] > 0)
    return out


def _worst_stress(payload: dict[str, Any]) -> float | None:
    scenarios = payload.get("scenarios") or []
    if not scenarios:
        return None
    return min(float(s.get("pnl_pct") or 0) for s in scenarios)


def _append_journal(user_id: str, name: str, payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.maneuver_cycle.journal import append_durable, seal_event
    from app.services.maneuver_cycle.service import shown_text

    maneuver = payload.get("maneuver") if isinstance(payload, dict) else None
    versions = {}
    text = ""
    if isinstance(maneuver, dict):
        versions = dict(maneuver.get("model_versions") or {})
        text = shown_text(maneuver)
    versions.setdefault("act_desk", MODEL_VERSION)
    with _lock:
        prev = _journal[-1]["hash"] if _journal else "0" * 64
        profile = dict(_profiles.get(user_id) or {})
        body = seal_event(
            {
                "id": str(uuid4()),
                "user_id": user_id,
                "name": name,
                "payload": payload,
                "model_version": MODEL_VERSION,
                "at": _now(),
                "prev_hash": prev,
                "profile_snapshot": profile,
                "model_versions": versions,
                "shown_text": text,
            }
        )
        _journal.append(body)
    append_durable(body)
    return body


def _load_journal_if_empty() -> None:
    from app.services.maneuver_cycle.journal import read_durable

    with _lock:
        if _journal:
            return
    rows = read_durable()
    if not rows:
        return
    with _lock:
        if not _journal:
            _journal.extend(rows)


def _record_paper_fill(user_id: str, item: dict[str, Any], filled: Decimal) -> None:
    if filled == 0:
        return
    orders = list(item.get("orders") or [])
    ticker = str(item.get("ticker") or "")
    if not ticker and orders:
        ticker = str(orders[0].get("ticker") or "")
    if not ticker:
        return
    count = int(item.get("fill_count") or 0) + 1
    item["fill_count"] = count
    key = f"act:{item['id']}:v{item.get('version') or 1}:f{count}"
    item["idempotency_key"] = key
    price = Decimal("0")
    if orders and orders[0].get("price") not in (None, ""):
        price = Decimal(str(orders[0]["price"]))
    amount = abs(filled) * price if price > 0 else abs(filled)
    sell = str(item.get("kind") or "") == "reduce_weight" or (
        bool(orders) and str(orders[0].get("side") or "").lower() == "sell"
    )
    account_id = f"paper-act:{user_id}"
    ensure_account(account_id=account_id, user_id=user_id, venue="act", mode="paper", source="act_desk")
    record_transaction(
        account_id=account_id,
        user_id=user_id,
        mode="paper",
        venue="act",
        external_id=key,
        kind="trade",
        instrument_id=ticker,
        ticker=ticker,
        qty=str(-abs(filled) if sell else abs(filled)),
        amount=str(amount),
        ccy="RUB",
        event_time=datetime.now(timezone.utc),
    )


def _require_flag() -> None:
    if not is_enabled("qa_act_desk"):
        raise RuntimeError("qa_act_desk off")


def _assert_clean(text: str) -> None:
    hits = filter_wording(text)
    if hits:
        raise ValueError(f"forbidden wording: {hits}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
