"""60: before/after table. Numbers from concentration + K4 what-if. No buy/sell button."""
from __future__ import annotations

from threading import Lock
from typing import Any
from uuid import uuid4

from app.services.concentration.service import analyze_portfolio
from app.services.fund_report.islands import attach_islands
from app.services.legal.catalog import load_ui_texts
from app.services.qa.feature_flags import is_enabled
from app.services.risk_engine.service import compute_risk_for_user, compute_what_if

_lock = Lock()
_scenarios: dict[str, list[dict[str, Any]]] = {}


def _pending(name: str) -> dict[str, Any]:
    return {"status": "будет доступно", "module": name, "values": None}


def check_basket(*, user_id: str, mode: str, trades: list[dict[str, Any]], funding: str | None = None) -> dict[str, Any]:
    if not is_enabled("qa_60_pretrade"):
        raise RuntimeError("qa_60_pretrade off")
    if len(trades) > 10:
        raise ValueError("корзина до 10 строк")
    texts = load_ui_texts().get("d60") or {}
    before_conc = analyze_portfolio(user_id=user_id, mode=mode)
    before_risk = compute_risk_for_user(user_id, mode)
    add: list[dict[str, Any]] = []
    remove: list[str] = []
    for row in trades:
        side = str(row.get("side") or "buy")
        ticker = str(row.get("ticker") or "").upper()
        if side == "sell" and row.get("qty") in {None, "", "0"} and row.get("close") is True:
            remove.append(ticker)
            continue
        if side == "sell":
            qty = f"-{row.get('qty') or row.get('amount') or '0'}"
        else:
            qty = str(row.get("qty") or row.get("amount") or "0")
        add.append({"ticker": ticker, "qty": qty, "price": row.get("price"), "ccy": row.get("ccy") or "RUB"})
    after_risk = compute_what_if(user_id=user_id, mode=mode, add=add or None, remove=remove or None)
    after_hhi = after_risk.get("hhi")
    costs = _pending("62")
    if is_enabled("qa_62_costs"):
        from app.services.total_costs.service import analyze_costs

        costs = {"status": "ok", "data": analyze_costs(user_id=user_id, mode=mode)}
    islands = attach_islands(user_id=user_id, mode=mode)
    return {
        "data_status": "ok" if before_risk.get("var_95") is not None else "частично",
        "texts": texts,
        "funding": funding,
        "methodology": "/methodology/pretrade",
        "no_order_button": True,
        "before": {
            "hhi": before_conc.get("hhi"),
            "weights": before_conc.get("weights"),
            "var_95": before_risk.get("var_95"),
            "es_975": before_risk.get("es_975"),
            "attribution": before_risk.get("attribution"),
        },
        "after": {
            "var_95": after_risk.get("var_95"),
            "es_975": after_risk.get("es_975"),
            "attribution": after_risk.get("attribution"),
            "hhi": after_hhi,
        },
        "blocks": {
            "structure": {"status": "ok", "source": "concentration"},
            "risk": {"status": "ok", "source": "K4 compute_what_if"},
            "factors": islands["factors"],
            "stress_rate": islands["stress_rate"],
            "liquidity": islands["liquidity"],
            "income": islands["income"],
            "tax": _pending("K3"),
            "costs": costs,
            "look_through": islands["look_through"],
            "futures": islands["futures"],
            "goals": islands["goals"],
            "bonds": islands["bonds"],
        },
    }


def save_scenario(*, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    row = {"id": str(uuid4()), **payload}
    with _lock:
        _scenarios.setdefault(user_id, []).append(row)
    return row


def list_scenarios(*, user_id: str) -> list[dict[str, Any]]:
    with _lock:
        return list(_scenarios.get(user_id) or [])
