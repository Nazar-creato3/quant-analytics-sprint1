"""Calls into public module functions. One failure does not stop the rest."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)

Source = Callable[[str, str, str, dict[str, Any]], dict[str, Any]]


def _risk(user_id: str, mode: str, portfolio_id: str, extra: dict[str, Any]) -> dict[str, Any]:
    del portfolio_id, extra
    from app.services.risk_engine.service import compute_risk_for_user

    payload = compute_risk_for_user(user_id, mode)
    if not payload.get("data_status"):
        payload = {**payload, "data_status": "ok" if payload.get("var_95") is not None else "нет данных"}
    return payload


def _k6(user_id: str, mode: str, portfolio_id: str, extra: dict[str, Any]) -> dict[str, Any]:
    del portfolio_id, extra
    from app.services.fund_report.metrics import fund_metrics
    from app.services.risk_engine.service import compute_risk_for_user

    risk = compute_risk_for_user(user_id, mode)
    return fund_metrics(risk.get("daily_returns") or [], attribution=risk.get("attribution"))


def _k1(user_id: str, mode: str, portfolio_id: str, extra: dict[str, Any]) -> dict[str, Any]:
    del portfolio_id, extra
    from app.services.benchmark_alt.service import compare_simple_alternatives

    return compare_simple_alternatives(user_id=user_id, mode=mode)


def _d59(user_id: str, mode: str, portfolio_id: str, extra: dict[str, Any]) -> dict[str, Any]:
    del portfolio_id, extra
    from app.services.decisions_report.service import analyze_decisions

    return analyze_decisions(user_id=user_id, mode=mode)


def _d62(user_id: str, mode: str, portfolio_id: str, extra: dict[str, Any]) -> dict[str, Any]:
    del portfolio_id, extra
    from app.services.total_costs.service import analyze_costs

    return analyze_costs(user_id=user_id, mode=mode)


def _d60(user_id: str, mode: str, portfolio_id: str, extra: dict[str, Any]) -> dict[str, Any]:
    del portfolio_id
    from app.services.pretrade_check.service import check_basket

    trades = list(extra.get("trades") or [])
    payload = check_basket(user_id=user_id, mode=mode, trades=trades)
    payload["trades"] = trades
    return payload


def _d56(user_id: str, mode: str, portfolio_id: str, extra: dict[str, Any]) -> dict[str, Any]:
    del mode, extra
    from app.services.bonds.service import portfolio_bonds

    return portfolio_bonds(user_id, portfolio_id)


def _d57(user_id: str, mode: str, portfolio_id: str, extra: dict[str, Any]) -> dict[str, Any]:
    del mode, extra
    from app.services.payouts.service import cashflow_summary

    return cashflow_summary(user_id, portfolio_id)


def _d64(user_id: str, mode: str, portfolio_id: str, extra: dict[str, Any]) -> dict[str, Any]:
    del mode, extra
    from app.services.position_liquidity.service import portfolio_liquidity

    return portfolio_liquidity(user_id, portfolio_id)


def _d61(user_id: str, mode: str, portfolio_id: str, extra: dict[str, Any]) -> dict[str, Any]:
    del portfolio_id, extra
    from app.services.fund_lookthrough.service import lookthrough_portfolio

    return lookthrough_portfolio(user_id, mode=mode)


def _k3(user_id: str, mode: str, portfolio_id: str, extra: dict[str, Any]) -> dict[str, Any]:
    del portfolio_id, extra
    from app.services.tax_ru.service import explain_tax

    return explain_tax(user_id, mode=mode)


def _d65(user_id: str, mode: str, portfolio_id: str, extra: dict[str, Any]) -> dict[str, Any]:
    del portfolio_id, extra
    from app.services.factor_lens.service import explain_portfolio

    return explain_portfolio(user_id, mode=mode)


def _d63(user_id: str, mode: str, portfolio_id: str, extra: dict[str, Any]) -> dict[str, Any]:
    del portfolio_id, extra
    from app.services.key_rate.service import explain_shift

    return explain_shift(user_id, mode=mode)


def _d58a(user_id: str, mode: str, portfolio_id: str, extra: dict[str, Any]) -> dict[str, Any]:
    del user_id, mode, portfolio_id
    from app.services.futures_risk.service import explain

    positions = list(extra.get("futures") or [])
    return explain(positions=positions, liquid_nav=extra.get("liquid_nav"))


def _d58b(user_id: str, mode: str, portfolio_id: str, extra: dict[str, Any]) -> dict[str, Any]:
    del user_id, mode, portfolio_id
    from app.services.futures_market.service import explain_market

    ticker = extra.get("futures_ticker") or extra.get("ticker")
    if not ticker:
        rows = list(extra.get("futures") or [])
        first = rows[0] if rows else None
        if isinstance(first, dict):
            ticker = first.get("ticker") or first.get("symbol")
        elif first:
            ticker = str(first)
    if not ticker:
        return {"data_status": "нет данных", "reason": "нет данных"}
    return explain_market(str(ticker))


def _k5(user_id: str, mode: str, portfolio_id: str, extra: dict[str, Any]) -> dict[str, Any]:
    del portfolio_id
    from decimal import Decimal, InvalidOperation

    from app.services.goals.service import explain_goal

    amount = extra.get("goal_amount")
    target = extra.get("goal_date")
    if amount is None or not target:
        return {"data_status": "нет данных", "reason": "нет цели в запросе"}
    try:
        amount_dec = amount if isinstance(amount, Decimal) else Decimal(str(amount))
    except (InvalidOperation, ValueError, TypeError):
        return {"data_status": "нет данных", "reason": "нет цели в запросе"}
    return explain_goal(user_id, target_amount=amount_dec, target_date=str(target), mode=mode)


def default_sources() -> dict[str, Source]:
    return {
        "risk": _risk,
        "k6": _k6,
        "k1": _k1,
        "d59": _d59,
        "d62": _d62,
        "d60": _d60,
        "d56": _d56,
        "d57": _d57,
        "d64": _d64,
        "d61": _d61,
        "k3": _k3,
        "d65": _d65,
        "d63": _d63,
        "d58a": _d58a,
        "d58b": _d58b,
        "k5": _k5,
    }


def gather(
    user_id: str,
    mode: str,
    portfolio_id: str,
    extra: dict[str, Any],
    sources: dict[str, Source],
    *,
    timeout_s: float = 8.0,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, str]]]:
    payloads: dict[str, dict[str, Any]] = {}
    missing: list[dict[str, str]] = []
    deadline = time.monotonic() + timeout_s

    def _run(fn: Source, box: dict[str, Any]) -> None:
        try:
            box["value"] = fn(user_id, mode, portfolio_id, extra)
        except Exception as exc:  # noqa: BLE001 — сбой одного модуля не обнуляет список
            box["error"] = type(exc).__name__

    started: list[tuple[str, threading.Thread, dict[str, Any]]] = []
    for key, fn in sources.items():
        box: dict[str, Any] = {}
        thread = threading.Thread(target=_run, args=(fn, box), daemon=True)
        thread.start()
        started.append((key, thread, box))
    for key, thread, box in started:
        remaining = deadline - time.monotonic()
        if remaining > 0:
            thread.join(remaining)
        if thread.is_alive():
            log.warning("decision_core source timeout module=%s", key)
            missing.append({"module": key, "reason": "нет данных"})
            payloads[key] = {"data_status": "нет данных", "reason": "дольше лимита"}
        elif "error" in box:
            log.warning("decision_core source failed module=%s error=%s", key, box["error"])
            missing.append({"module": key, "reason": "нет данных"})
            payloads[key] = {"data_status": "нет данных", "reason": str(box["error"])}
        else:
            payloads[key] = box.get("value") or {"data_status": "нет данных"}
    return payloads, missing
