"""Result control for maneuvers (Prompt 40).

Attribution uses a supplied price path. A missing path is «нет данных».
Profile limits are not loosened by approval rates.
Methodology: docs/methodology/maneuver-control.md
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from threading import Lock
from typing import Any

from app.services.qa.feature_flags import is_enabled

MODEL_VERSION = "maneuver_control.v1"
_MISSING = "нет данных"
_EXECUTED = {"executed_full", "executed_partial", "executed_paper", "closed"}
_REJECTED = {"rejected"}
_lock = Lock()
_errors: dict[str, list[Decimal]] = {}
_seen: set[str] = set()
_rejections: dict[str, int] = {}
_edits: dict[str, int] = {}
_reason_counts: dict[str, int] = {}
_paths: dict[str, dict[str, list[str]]] = {}


def reset() -> None:
    with _lock:
        _errors.clear()
        _seen.clear()
        _rejections.clear()
        _edits.clear()
        _reason_counts.clear()
        _paths.clear()


def load_rule() -> dict[str, Any]:
    raw = json.loads(Path(__file__).with_name("config.json").read_text(encoding="utf-8"))
    return {
        "min_samples": int(raw["min_samples"]),
        "abs_error_beta": Decimal(str(raw["abs_error_beta"])),
        "abs_error_off": Decimal(str(raw["abs_error_off"])),
        "max_rank_penalty": Decimal(str(raw["max_rank_penalty"])),
        "penalty_step": Decimal(str(raw["penalty_step"])),
    }


def remember_path(maneuver_id: str, prices: dict[str, list[str]]) -> None:
    """Store a price path the caller already has. This function does not fetch prices."""
    cleaned: dict[str, list[str]] = {}
    for ticker, series in prices.items():
        if not series:
            continue
        cleaned[str(ticker).upper()] = [str(point) for point in series]
    with _lock:
        _paths[maneuver_id] = cleaned


def note_decision(item: dict[str, Any]) -> None:
    """Rejection and edit counts. They can only lower a rank score."""
    if not is_enabled("qa_maneuver_control"):
        return
    kind = str(item.get("kind") or "")
    if not kind:
        return
    status = str(item.get("status") or "")
    with _lock:
        if status == "rejected":
            _rejections[kind] = _rejections.get(kind, 0) + 1
            code = str(item.get("reject_reason") or "")
            if code:
                _reason_counts[code] = _reason_counts.get(code, 0) + 1
        elif status == "edited":
            _edits[kind] = _edits.get(kind, 0) + 1


def kind_status(kind: str) -> dict[str, Any]:
    """Ready, beta, off, or нет данных. Same shape as the 11B status switch."""
    rule = load_rule()
    with _lock:
        sample = list(_errors.get(kind) or [])
    if len(sample) < rule["min_samples"]:
        return {"kind": kind, "status": _MISSING, "n": len(sample), "mean_abs_error": None, "reason": _MISSING}
    mean_abs = sum((abs(err) for err in sample), Decimal(0)) / Decimal(len(sample))
    if mean_abs >= rule["abs_error_off"]:
        state, reason = "off", "средняя ошибка ожидаемого эффекта выше порога отключения"
    elif mean_abs >= rule["abs_error_beta"]:
        state, reason = "beta", "средняя ошибка ожидаемого эффекта выше порога беты"
    else:
        state, reason = "ready", "ошибка внутри порога"
    return {
        "kind": kind,
        "status": state,
        "n": len(sample),
        "mean_abs_error": format(mean_abs, "f"),
        "reason": reason,
    }


def score_delta(kind: str) -> Decimal:
    """Non-positive. Approval rate is not an input."""
    rule = load_rule()
    with _lock:
        n = _rejections.get(kind, 0) + _edits.get(kind, 0)
    penalty = rule["penalty_step"] * Decimal(n)
    penalty = min(penalty, rule["max_rank_penalty"])
    return -penalty


def gate_candidate(cand: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """Drop an off kind. Never raise the score and never edit profile limits."""
    if not is_enabled("qa_maneuver_control"):
        return cand, None
    kind = str(cand.get("kind") or "")
    state = kind_status(kind)
    if state["status"] == "off":
        return None, state["reason"]
    updated = dict(cand)
    if state["status"] == "beta":
        updated["quality"] = "beta"
        updated["quality_reason"] = state["reason"]
    delta = score_delta(kind)
    if delta < 0 and updated.get("score") not in (None, ""):
        updated["score"] = format(Decimal(str(updated["score"])) + delta, "f")
        updated["rank_note"] = "оценка снижена по отказам и правкам; лимит профиля не изменён"
    return updated, None


def attribute(
    item: dict[str, Any],
    prices: dict[str, list[str]] | None,
) -> dict[str, Any]:
    """Actual horizon versus expected and versus doing nothing.

    Rejected rows report the path that was not taken. Numbers are strings.
    """
    book = _book(item)
    orders = list(item.get("orders") or [])
    expected = _decimal(item.get("expected_return"))
    status = str(item.get("status") or "")
    done = _returns(book, orders, prices)
    actual_key = "counterfactual_return" if status in _REJECTED else "actual_return"
    row: dict[str, Any] = {
        "maneuver_id": item.get("id"),
        "kind": item.get("kind"),
        "status": status,
        "expected_return": _num(expected),
        "do_nothing_return": _num(done.get("do_nothing")),
        actual_key: _num(done.get("traded")),
        "risk": _risk_block(item, done.get("after_holdings")),
        "quality": kind_status(str(item.get("kind") or "")),
    }
    if status in _REJECTED:
        row["actual_return"] = _num(done.get("do_nothing"))
        row["note"] = "манёвр отклонён; фактический путь — бездействие"
    elif status in _EXECUTED or status == "sent":
        row["note"] = "исполненный путь против бездействия"
    else:
        row["note"] = _MISSING
    traded = done.get("traded")
    if expected is not None and traded is not None and status not in _REJECTED:
        row["error"] = format(traded - expected, "f")
    elif expected is not None and status in _REJECTED and traded is not None:
        row["counterfactual_error"] = format(traded - expected, "f")
    else:
        row["error"] = None
        row["error_status"] = _MISSING
    _remember_error(item, row)
    return row


def user_report(user_id: str) -> dict[str, Any]:
    if not is_enabled("qa_maneuver_control"):
        return {"status": "off", "items": [], "model_version": MODEL_VERSION}
    from app.services.act_desk.service import list_maneuvers

    items = []
    for item in list_maneuvers(user_id):
        if str(item.get("status") or "") not in _EXECUTED | _REJECTED:
            continue
        with _lock:
            path = _paths.get(str(item.get("id")))
        items.append(attribute(dict(item), path))
    return {
        "status": "ready" if items else _MISSING,
        "items": items,
        "model_version": MODEL_VERSION,
        "source": "maneuver_control",
    }


def aggregate() -> dict[str, Any]:
    """Counts only. No user id and no free-text notes."""
    if not is_enabled("qa_maneuver_control"):
        return {"status": "off", "model_version": MODEL_VERSION}
    with _lock:
        reasons = dict(_reason_counts)
        errors = {kind: list(sample) for kind, sample in _errors.items()}
        rejections = dict(_rejections)
    by_kind: dict[str, Any] = {}
    paired = 0
    abs_sum = Decimal(0)
    close = 0
    for kind, sample in errors.items():
        state = kind_status(kind)
        decided = len(sample) + rejections.get(kind, 0)
        share = format(Decimal(len(sample)) / Decimal(decided), "f") if decided else None
        by_kind[kind] = {
            "status": state["status"],
            "n_errors": len(sample),
            "mean_abs_error": state["mean_abs_error"],
            "rejections": rejections.get(kind, 0),
            "executed_share": share if share is not None else _MISSING,
        }
        for err in sample:
            paired += 1
            abs_sum += abs(err)
            if abs(err) <= Decimal("0.02"):
                close += 1
    accuracy = format(abs_sum / Decimal(paired), "f") if paired else None
    calibration = format(Decimal(close) / Decimal(paired), "f") if paired else None
    payload = {
        "status": "ready" if by_kind or reasons else _MISSING,
        "model_version": MODEL_VERSION,
        "by_kind": by_kind,
        "reject_reasons": reasons,
        "mean_abs_error": accuracy if accuracy is not None else _MISSING,
        "calibration_share_within_0_02": calibration if calibration is not None else _MISSING,
        "history": history_handoff(),
        "priority": "лимиты профиля важнее доли одобрений",
    }
    blob = json.dumps(payload, ensure_ascii=False)
    if "user_id" in blob:
        raise RuntimeError("aggregate leaked user_id")
    return payload


def history_handoff(path: Path | None = None) -> dict[str, Any]:
    file = path or Path(__file__).resolve().parents[4] / "docs" / "models" / "maneuver-history-control.json"
    if not file.exists():
        return {"status": _MISSING}
    from app.services.maneuver_history.handoff import read_control_input

    data = read_control_input(file)
    return {
        "status": "прочитан",
        "schema": data.get("schema"),
        "seed": data.get("seed"),
        "target_source": data.get("target_source"),
        "scenario_count": len(data.get("scenarios") or []),
    }


def limits_unchanged(before: dict[str, Any], after: dict[str, Any]) -> bool:
    keys = ("max_position_pct", "max_crisis_loss_pct", "max_single_weight")
    return all(str(before.get(key)) == str(after.get(key)) for key in keys)


def _remember_error(item: dict[str, Any], row: dict[str, Any]) -> None:
    mid = str(item.get("id") or "")
    raw = row.get("error")
    if raw in (None, "") or not mid:
        return
    with _lock:
        if mid in _seen:
            return
        _seen.add(mid)
        _errors.setdefault(str(item.get("kind") or ""), []).append(Decimal(str(raw)))


def _book(item: dict[str, Any]) -> dict[str, Decimal]:
    book: dict[str, Decimal] = {}
    for row in item.get("holdings") or []:
        ticker = str(row.get("ticker") or "").upper()
        if ticker:
            book[ticker] = Decimal(str(row.get("qty") or "0"))
    return book


def _returns(
    book: dict[str, Decimal],
    orders: list[dict[str, Any]],
    prices: dict[str, list[str]] | None,
) -> dict[str, Any]:
    if not prices or not book:
        return {"do_nothing": None, "traded": None, "after_holdings": None}
    start, end = _ends(prices)
    if start is None or end is None:
        return {"do_nothing": None, "traded": None, "after_holdings": None}
    cash0 = Decimal(str(book.get("CASH") or book.get("cash") or 0))
    book_qty = {k: v for k, v in book.items() if str(k).upper() != "CASH"}
    start_value = _value(book_qty, start, cash0)
    do_nothing_end = _value(book_qty, end, cash0)
    traded_qty, cash = _apply(book, orders, start)
    if traded_qty is None or start_value is None or start_value == 0 or do_nothing_end is None:
        return {"do_nothing": None, "traded": None, "after_holdings": None}
    traded_end = _value(traded_qty, end, cash)
    if traded_end is None:
        return {"do_nothing": None, "traded": None, "after_holdings": None}
    holdings = [
        {"ticker": ticker, "qty": format(qty, "f"), "price": format(end[ticker], "f"), "ccy": "RUB"}
        for ticker, qty in traded_qty.items()
        if qty > 0 and ticker in end
    ]
    return {
        "do_nothing": (do_nothing_end - start_value) / start_value,
        "traded": (traded_end - start_value) / start_value,
        "after_holdings": holdings,
    }


def _ends(prices: dict[str, list[str]]) -> tuple[dict[str, Decimal] | None, dict[str, Decimal] | None]:
    start: dict[str, Decimal] = {}
    end: dict[str, Decimal] = {}
    for ticker, series in prices.items():
        if len(series) < 2:
            return None, None
        start[ticker.upper()] = Decimal(str(series[0]))
        end[ticker.upper()] = Decimal(str(series[-1]))
    return start, end


def _apply(
    book: dict[str, Decimal],
    orders: list[dict[str, Any]],
    start: dict[str, Decimal],
) -> tuple[dict[str, Decimal] | None, Decimal]:
    """Apply orders using book cash. Do not invent cash from a zero base for buys."""
    qty = {k: v for k, v in book.items() if str(k).upper() != "CASH"}
    cash = Decimal(str(book.get("CASH") or book.get("cash") or 0))
    for order in orders:
        ticker = str(order.get("ticker") or "").upper()
        if ticker not in start or order.get("price") in (None, ""):
            return None, Decimal(0)
        size = abs(Decimal(str(order.get("qty") or "0")))
        price = Decimal(str(order["price"]))
        if str(order.get("side") or "").lower() == "sell":
            qty[ticker] = qty.get(ticker, Decimal(0)) - size
            cash += size * price
        else:
            cost = size * price
            if cash < cost:
                return None, Decimal(0)
            qty[ticker] = qty.get(ticker, Decimal(0)) + size
            cash -= cost
    return qty, cash


def _value(qty: dict[str, Decimal], prices: dict[str, Decimal], cash: Decimal) -> Decimal | None:
    total = cash
    for ticker, size in qty.items():
        if size == 0:
            continue
        px = prices.get(ticker)
        if px is None:
            return None
        total += size * px
    return total


def _risk_block(item: dict[str, Any], holdings: list[dict[str, Any]] | None) -> dict[str, Any]:
    expected = ((item.get("impact") or {}).get("delta") or {}).get("var_95") or {}
    block: dict[str, Any] = {
        "expected_var_95_before": expected.get("before") if expected.get("before") is not None else _MISSING,
        "expected_var_95_after": expected.get("after") if expected.get("after") is not None else _MISSING,
        "actual_var_95": _MISSING,
    }
    if not holdings:
        return block
    try:
        from app.services.risk_engine.service import compute_risk_for_holdings

        payload = compute_risk_for_holdings(holdings)
    except (RuntimeError, ValueError, TypeError, KeyError):
        return block
    var = payload.get("var_95")
    if var is None:
        return block
    block["actual_var_95"] = str(var)
    return block


def _decimal(value: Any) -> Decimal | None:
    if value in (None, "", _MISSING):
        return None
    return Decimal(str(value))


def _num(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value, "f")
