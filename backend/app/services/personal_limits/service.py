"""User-defined risk thresholds (Prompt 21, [ЮРИСТ], default off)."""
from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from typing import Any

from app.services.concentration.service import analyze_portfolio
from app.services.event_bus.bus import publish_event
from app.services.qa.feature_flags import is_enabled
from app.services.risk_engine.service import compute_risk_for_user
from app.services.stress_library.service import run_portfolio

_lock = Lock()
_limits: dict[str, dict[str, Any]] = {}
_breaches: dict[str, list[dict[str, Any]]] = {}


def reset() -> None:
    with _lock:
        _limits.clear()
        _breaches.clear()


def _require() -> None:
    if not is_enabled("qa_personal_limits"):
        raise RuntimeError("qa_personal_limits off")


def set_limits(*, user_id: str, crisis_loss: float | None, concentration: float | None, leverage: float | None, drawdown: float | None) -> dict[str, Any]:
    _require()
    row = {
        "crisis_loss": crisis_loss,
        "concentration": concentration,
        "leverage": leverage,
        "drawdown": drawdown,
        "as_of": datetime.now(timezone.utc).isoformat(),
    }
    with _lock:
        _limits[user_id] = row
    return get_limits(user_id=user_id)


def get_limits(*, user_id: str) -> dict[str, Any]:
    _require()
    with _lock:
        row = _limits.get(user_id)
    if not row:
        return {"data_status": "нет данных", "limits": None, "user_id": user_id}
    return {"data_status": "ok", "limits": row, "user_id": user_id}


def evaluate_limits(*, user_id: str, mode: str = "paper") -> dict[str, Any]:
    _require()
    got = get_limits(user_id=user_id)
    limits = got.get("limits")
    if not limits:
        return {"data_status": "нет данных", "hits": [], "user_id": user_id}
    risk = compute_risk_for_user(user_id, mode)
    conc = analyze_portfolio(user_id=user_id, mode=mode)
    stress = run_portfolio(user_id=user_id, mode=mode)
    hits: list[dict[str, Any]] = []
    crisis = None
    for row in stress.get("scenarios") or []:
        if row.get("id") in {"2020", "2022_feb_mar"}:
            crisis = row
            break
    if limits.get("crisis_loss") is not None and crisis is not None:
        pnl = crisis.get("pnl_pct", crisis.get("pnl"))
        try:
            if abs(float(pnl)) > abs(float(limits["crisis_loss"])):
                hits.append({"rule": "crisis_loss", "value": pnl, "threshold": limits["crisis_loss"]})
        except (TypeError, ValueError):
            pass
    if limits.get("concentration") is not None and conc.get("hhi") is not None:
        try:
            if float(conc["hhi"]) > float(limits["concentration"]):
                hits.append({"rule": "concentration", "value": conc["hhi"], "threshold": limits["concentration"]})
        except (TypeError, ValueError):
            pass
    if limits.get("drawdown") is not None and risk.get("max_drawdown") is not None:
        try:
            if float(risk["max_drawdown"]) > float(limits["drawdown"]):
                hits.append({"rule": "drawdown", "value": risk["max_drawdown"], "threshold": limits["drawdown"]})
        except (TypeError, ValueError):
            pass
    if limits.get("leverage") is not None:
        hits.extend(_leverage_hits(user_id, mode, float(limits["leverage"])))
    now = datetime.now(timezone.utc).isoformat()
    for hit in hits:
        rec = {**hit, "user_id": user_id, "mode": mode, "as_of": now}
        with _lock:
            _breaches.setdefault(user_id, []).append(rec)
        try:
            publish_event("risk.limit_breached", {"user_id": user_id, "rule": hit["rule"]})
        except Exception:
            pass
    return {"data_status": "ok", "hits": hits, "user_id": user_id, "mode": mode}


def breaches(*, user_id: str) -> list[dict[str, Any]]:
    _require()
    with _lock:
        return list(_breaches.get(user_id) or [])


def user_rule_reasons(*, user_id: str, mode: str = "paper") -> list[str]:
    if not is_enabled("qa_personal_limits"):
        return []
    try:
        out = evaluate_limits(user_id=user_id, mode=mode)
    except Exception:
        return []
    return [f"личный лимит: {h['rule']}" for h in out.get("hits") or []]


def _leverage_hits(user_id: str, mode: str, threshold: float) -> list[dict[str, Any]]:
    """Gross long notional / NAV in money terms — never sum raw share counts."""
    from app.services.concentration.service import _trade_price
    from app.services.portfolio_book.store import get_book

    pos = get_book().positions(user_id=user_id, mode=mode)  # type: ignore[arg-type]
    long_money = 0.0
    cash_money = 0.0
    for p in pos:
        qty = float(p.qty)
        if p.ticker.upper() == "CASH":
            cash_money += qty
            continue
        px = _trade_price(user_id, mode, p.ticker)
        if px is None:
            return []  # cannot claim leverage without marks
        long_money += abs(qty) * float(px)
    nav = cash_money + long_money
    if nav <= 0:
        return []
    lev = long_money / nav
    if lev > threshold:
        return [{"rule": "leverage", "value": lev, "threshold": threshold}]
    return []
