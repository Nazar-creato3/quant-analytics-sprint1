"""User actions on a maneuver record (Prompt 39).

Impact after an edit is `act_desk.preview_orders` (the same pretrade path).
Live orders are not sent: `qa_act_live` stays off, and the order machine is prompt 24.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.services.maneuver_cycle.machine import (
    REJECT_REASONS,
    assert_transition,
)

_MISSING = "нет данных"


def shown_text(item: dict[str, Any]) -> str:
    logic = item.get("logic") if isinstance(item.get("logic"), dict) else {}
    parts = [
        str(item.get("rationale") or ""),
        str((logic or {}).get("phrase") or ""),
        str(item.get("disclaimer") or ""),
    ]
    return "\n".join(part for part in parts if part)


def diff_composition(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Field-level difference between the original orders and the edited ones."""
    def key(row: dict[str, Any], index: int) -> str:
        ticker = str(row.get("ticker") or "")
        side = str(row.get("side") or "")
        return f"{index}:{ticker}:{side}"

    before_map = {key(row, i): row for i, row in enumerate(before)}
    after_map = {key(row, i): row for i, row in enumerate(after)}
    changes: list[dict[str, str]] = []
    for name in sorted(set(before_map) | set(after_map)):
        left = before_map.get(name) or {}
        right = after_map.get(name) or {}
        fields = sorted(set(left) | set(right))
        for field in fields:
            old = "" if field not in left else str(left.get(field))
            new = "" if field not in right else str(right.get(field))
            if old != new:
                changes.append({"line": name, "field": field, "before": old or _MISSING, "after": new or _MISSING})
    return changes


def apply_action(
    item: dict[str, Any],
    action: str,
    *,
    edits: dict[str, Any] | None = None,
    confirm: bool = False,
    reject_reason: str | None = None,
    reject_note: str = "",
    mode: str = "paper",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return an updated record. Does not persist it."""
    current = str(item.get("status") or "")
    if action == "view":
        assert_transition(current, "viewed")
        item["status"] = "viewed"
        item["viewed_at"] = _iso(now)
        return item
    if action == "edit":
        return _edit(item, edits or {}, mode=mode, now=now)
    if action == "approve":
        return _approve(item, confirm=confirm, now=now)
    if action == "reject":
        return _reject(item, reason=reject_reason, note=reject_note, now=now)
    if action == "expire":
        assert_transition(current, "expired")
        item["status"] = "expired"
        item["expired_at"] = _iso(now)
        item["expiry_reason"] = str((edits or {}).get("reason") or "истёк срок")
        return item
    raise ValueError("action")


def recheck_before_send(item: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Re-read prices. Missing price or a passed deadline blocks sending."""
    moment = now or datetime.now(UTC)
    orders = list(item.get("orders") or [])
    if not orders:
        return {"ok": False, "reason": _MISSING, "checked": []}
    if not item.get("expires_at"):
        return {"ok": False, "reason": _MISSING, "checked": []}
    checked: list[dict[str, str]] = []
    prices: dict[str, Decimal] = {}
    for order in orders:
        ticker = str(order.get("ticker") or "").upper()
        price, tag = _fresh_price(ticker, order)
        if price is None:
            return {"ok": False, "reason": _MISSING, "ticker": ticker, "checked": checked}
        prices[ticker] = price
        checked.append(
            {
                "ticker": ticker,
                "price": format(price, "f"),
                "license_tag": tag,
            }
        )
    from app.services.maneuvers.service import maneuver_expired

    expired, reason = maneuver_expired(item, now=moment, prices=prices)
    if expired:
        return {"ok": False, "expired": True, "reason": reason or "истёк срок", "checked": checked}
    return {"ok": True, "reason": "", "checked": checked}


def mark_sent(item: dict[str, Any], check: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    if check.get("expired"):
        assert_transition(str(item.get("status") or ""), "expired")
        item["status"] = "expired"
        item["expiry_reason"] = str(check.get("reason") or "истёк срок")
        item["price_check"] = check
        item["expired_at"] = _iso(now)
        return item
    if not check.get("ok"):
        item["price_check"] = check
        item["send_block"] = str(check.get("reason") or _MISSING)
        return item
    assert_transition(str(item.get("status") or ""), "sent")
    item["status"] = "sent"
    item["sent_at"] = _iso(now)
    item["price_check"] = check
    item["idempotency_key"] = f"act:{item['id']}:v{item.get('version') or 1}"
    return item


def mark_fill(
    item: dict[str, Any],
    *,
    filled_qty: Decimal,
    ordered_qty: Decimal,
    now: datetime | None = None,
) -> dict[str, Any]:
    if ordered_qty <= 0 or filled_qty <= 0:
        raise ValueError(_MISSING)
    if filled_qty > ordered_qty:
        raise ValueError("исполненный объём больше заявки")
    nxt = "executed_full" if filled_qty == ordered_qty else "executed_partial"
    assert_transition(str(item.get("status") or ""), nxt)
    item["status"] = nxt
    item["filled_qty"] = format(filled_qty, "f")
    item["ordered_qty"] = format(ordered_qty, "f")
    item["filled_at"] = _iso(now)
    return item


def mark_closed(item: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    assert_transition(str(item.get("status") or ""), "closed")
    item["status"] = "closed"
    item["closed_at"] = _iso(now)
    return item


def ordered_qty(item: dict[str, Any]) -> Decimal:
    orders = list(item.get("orders") or [])
    if orders:
        total = Decimal(0)
        for order in orders:
            total += abs(Decimal(str(order.get("qty") or "0")))
        return total
    return abs(Decimal(str(item.get("qty") or "0")))


def live_blocked(mode: str) -> None:
    """Paper is the only execution path. Live stays behind the lawyer flag and prompt 24."""
    if mode == "paper":
        return
    from app.services.qa.feature_flags import is_enabled

    if not is_enabled("qa_act_live"):
        raise PermissionError("live execution off until lawyer flag qa_act_live")
    raise PermissionError(
        "live: нужны LiveConfirm, двухфакторная аутентификация (28) и машина заявок (24); не подключено"
    )


def _edit(item: dict[str, Any], edits: dict[str, Any], *, mode: str, now: datetime | None) -> dict[str, Any]:
    assert_transition(str(item.get("status") or ""), "edited")
    if "original" not in item:
        item["original"] = {
            "qty": str(item.get("qty") or "0"),
            "ticker": str(item.get("ticker") or ""),
            "orders": deepcopy(list(item.get("orders") or [])),
        }
    orders = deepcopy(list(item.get("orders") or []))
    if "orders" in edits and isinstance(edits["orders"], list):
        orders = [dict(row) for row in edits["orders"]]
    elif "qty" in edits and orders:
        orders[0]["qty"] = str(edits["qty"])
    if "qty" in edits:
        item["qty"] = str(edits["qty"])
    if "ticker" in edits:
        item["ticker"] = str(edits["ticker"])
        if orders:
            orders[0]["ticker"] = str(edits["ticker"]).upper()
    item["orders"] = orders
    item["version"] = int(item.get("version") or 1) + 1
    item["status"] = "edited"
    item["edited_at"] = _iso(now)
    before = list((item.get("original") or {}).get("orders") or [])
    item["diff_vs_original"] = diff_composition(before, orders)
    item["impact"] = _reassess(item, orders, mode=mode)
    gate = (item["impact"] or {}).get("gate") if isinstance(item.get("impact"), dict) else None
    item["gate"] = gate
    return item


def _approve(item: dict[str, Any], *, confirm: bool, now: datetime | None) -> dict[str, Any]:
    if not confirm:
        raise ValueError("нужно явное подтверждение")
    gate = item.get("gate")
    if isinstance(gate, dict) and gate.get("verdict") == "block":
        raise ValueError("pretrade не пропускает правку")
    if item.get("status") == "edited" and item.get("impact_reason") == _MISSING and not item.get("orders"):
        raise ValueError(_MISSING)
    assert_transition(str(item.get("status") or ""), "approved")
    item["status"] = "approved"
    item["approved_at"] = _iso(now)
    item["confirmed"] = True
    return item


def _reject(item: dict[str, Any], *, reason: str | None, note: str, now: datetime | None) -> dict[str, Any]:
    if reason not in REJECT_REASONS:
        raise ValueError("причина отклонения не из списка")
    text = str(note or "").strip()
    if reason == "other" and not text:
        raise ValueError("для причины «другое» нужен текст")
    from app.services.explanations.service import filter_wording

    hits = filter_wording(text)
    if hits:
        raise ValueError(f"forbidden wording: {hits}")
    assert_transition(str(item.get("status") or ""), "rejected")
    item["status"] = "rejected"
    item["reject_reason"] = reason
    item["reject_reason_label"] = REJECT_REASONS[reason]
    item["reject_note"] = text
    item["rejected_at"] = _iso(now)
    return item


def _reassess(item: dict[str, Any], orders: list[dict[str, Any]], *, mode: str) -> dict[str, Any]:
    if not orders:
        item["impact_reason"] = _MISSING
        return {"reason": _MISSING, "delta": None, "costs": None, "gate": None}
    from app.services.act_desk.service import preview_orders

    impact = preview_orders(user_id=str(item["user_id"]), mode=mode, orders=orders)
    item["impact_reason"] = ""
    item["costs"] = impact.get("costs")
    return {
        "delta": impact.get("delta"),
        "costs": impact.get("costs"),
        "tax": impact.get("tax"),
        "gate": impact.get("gate"),
        "note": impact.get("note"),
    }


def _fresh_price(ticker: str, order: dict[str, Any]) -> tuple[Decimal | None, str]:
    from app.services.target_portfolio.service import load_market_price

    price, tag, allowed = load_market_price(ticker)
    if price is not None and allowed:
        return price, tag
    source = str(order.get("price_source") or "")
    if source in {"portfolio_book", "user_book"} and order.get("price") not in (None, ""):
        return Decimal(str(order["price"])), str(order.get("license_tag") or source)
    return None, tag or "internal_only"


def _iso(now: datetime | None) -> str:
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).isoformat()
