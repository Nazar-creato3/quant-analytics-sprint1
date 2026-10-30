"""What-if copy of a portfolio (Prompt 21). No money action, no advice."""
from __future__ import annotations

from threading import Lock
from time import perf_counter
from typing import Any

from app.services.concentration.service import analyze_holdings, analyze_portfolio
from app.services.explanations.service import filter_wording
from app.services.portfolio_book.store import get_book
from app.services.qa.feature_flags import is_enabled
from app.services.risk_engine.series import get_series
from app.services.risk_engine.service import as_dict, compute_risk
from app.services.risk_engine.euler import euler_allocate
from app.services.stress_library.service import run_holdings

_lock = Lock()
_variants: dict[str, list[dict[str, Any]]] = {}


def reset() -> None:
    with _lock:
        _variants.clear()


def _require() -> None:
    if not is_enabled("qa_sandbox"):
        raise RuntimeError("qa_sandbox off")


def simulate(
    *,
    user_id: str,
    mode: str = "paper",
    holdings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    _require()
    started = perf_counter()
    copy = _normalize(holdings) if holdings else _from_book(user_id, mode)
    empty = not copy
    conc = analyze_holdings(copy) if copy else {"empty": True, "weights": {}, "hhi": None}
    risk = _risk_from_holdings(copy)
    stress = run_holdings([{"ticker": h["ticker"], "value": float(h["qty"]) * float(h.get("price") or 1), "ccy": h.get("ccy") or "RUB"} for h in copy]) if copy else {"empty": True, "scenarios": []}
    baseline = {
        "risk": _safe_user_risk(user_id, mode),
        "concentration": analyze_portfolio(user_id=user_id, mode=mode),
    }
    note = "Копия портфеля. Это не заявка и не указание действовать."
    if filter_wording(note):
        note = "Копия портфеля для пересчёта риска."
    elapsed_ms = int((perf_counter() - started) * 1000)
    return {
        "source": "sandbox",
        "user_id": user_id,
        "mode": mode,
        "empty": empty,
        "data_status": "нет данных" if empty else "ok",
        "holdings": copy,
        "risk": risk,
        "concentration": conc,
        "stress": stress,
        "baseline": baseline,
        "delta": {
            "var_95": _delta(risk.get("var_95"), (baseline["risk"] or {}).get("var_95")),
            "hhi": _delta(conc.get("hhi"), (baseline["concentration"] or {}).get("hhi")),
        },
        "elapsed_ms": elapsed_ms,
        "disclaimer": note,
    }


def save_variant(*, user_id: str, name: str, payload: dict[str, Any]) -> dict[str, Any]:
    _require()
    row = {"name": name, "var_95": (payload.get("risk") or {}).get("var_95"), "hhi": (payload.get("concentration") or {}).get("hhi"), "holdings": payload.get("holdings")}
    with _lock:
        _variants.setdefault(user_id, []).append(row)
        n = len(_variants[user_id])
    return {"saved": True, "n": n, "variant": row}


def list_variants(*, user_id: str) -> list[dict[str, Any]]:
    _require()
    with _lock:
        return list(_variants.get(user_id) or [])


def compare(*, user_id: str) -> dict[str, Any]:
    _require()
    rows = list_variants(user_id=user_id)
    if not rows:
        return {"data_status": "нет данных", "variants": []}
    return {"data_status": "ok", "variants": rows}


def _normalize(holdings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for h in holdings:
        ticker = str(h.get("ticker") or "").upper()
        if not ticker or ticker == "CASH":
            continue
        out.append(
            {
                "ticker": ticker,
                "qty": str(h.get("qty") or "0"),
                "price": str(h.get("price") or "1"),
                "ccy": str(h.get("ccy") or "RUB"),
            }
        )
    return out


def _from_book(user_id: str, mode: str) -> list[dict[str, Any]]:
    book = get_book().positions(user_id=user_id, mode=mode)  # type: ignore[arg-type]
    return [{"ticker": p.ticker, "qty": str(abs(p.qty)), "price": "1", "ccy": p.ccy} for p in book if p.ticker != "CASH"]


def _risk_from_holdings(holdings: list[dict[str, Any]]) -> dict[str, Any]:
    tickers = [h["ticker"] for h in holdings]
    cols: list[list[float]] = []
    used: list[str] = []
    for t in tickers:
        s = get_series(t)
        if s:
            cols.append(s)
            used.append(t)
    if not cols:
        payload = as_dict(compute_risk([], tickers=tickers))
        payload["incomplete"] = True
        payload["data_status"] = "нет данных"
        return payload
    n = min(len(c) for c in cols)
    matrix = [c[-n:] for c in cols]
    weights = [1.0 / len(matrix)] * len(matrix)
    port = [sum(w * matrix[i][t] for i, w in enumerate(weights)) for t in range(n)]
    payload = as_dict(compute_risk(port, tickers=used))
    alloc = euler_allocate(list(map(list, zip(*matrix))), weights)
    payload["components"] = [
        {"ticker": used[i], "var": alloc["component_var"][i], "es": alloc["component_es"][i]}
        for i in range(len(used))
    ]
    payload["data_status"] = "ok"
    return payload


def _safe_user_risk(user_id: str, mode: str) -> dict[str, Any]:
    from app.services.risk_engine.service import compute_risk_for_user

    try:
        return compute_risk_for_user(user_id, mode)
    except Exception:
        return {"var_95": None, "data_status": "нет данных"}


def _delta(new: Any, old: Any) -> Any:
    try:
        return float(new) - float(old)
    except (TypeError, ValueError):
        return None
