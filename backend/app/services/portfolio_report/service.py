"""Portfolio report assembler (Prompt 17). Reads core services only."""
from __future__ import annotations

from datetime import UTC, datetime
from threading import Lock
from time import perf_counter
from typing import Any

from app.services.behavior.service import analyze_user
from app.services.concentration.service import analyze_portfolio
from app.services.explanations.service import filter_wording, render
from app.services.portfolio_book.store import get_book
from app.services.qa.feature_flags import is_enabled
from app.services.returns.service import as_dict as returns_as_dict
from app.services.returns.service import compute_returns, equity_vs_benchmark
from app.services.risk_engine.service import compute_risk_for_user
from app.services.stress_library.service import run_portfolio

CONFIG_VERSION = "portfolio_report.v1"
_lock = Lock()
_history: dict[str, list[dict[str, Any]]] = {}


def assemble(*, user_id: str, mode: str = "paper") -> dict[str, Any]:
    if not is_enabled("qa_report"):
        raise RuntimeError("qa_report off")
    started = perf_counter()
    now = datetime.now(UTC).isoformat()
    positions = get_book().positions(user_id=user_id, mode=mode)  # type: ignore[arg-type]
    empty = not positions
    returns = returns_as_dict(compute_returns(user_id=user_id, mode=mode, period="inception"))  # type: ignore[arg-type]
    risk = compute_risk_for_user(user_id, mode)
    conc = analyze_portfolio(user_id=user_id, mode=mode)
    stress = run_portfolio(user_id=user_id, mode=mode)
    behavior = analyze_user(user_id=user_id, mode=mode)
    headline = _headline(empty, risk, conc)
    queues = {
        "q1_composition": _block(conc, ready=not empty),
        "q2_var_stress": _block({"var_95": risk.get("var_95"), "stress": _core_stress(stress)}, ready=risk.get("var_95") is not None),
        "q3_returns": _block(returns, ready=not returns.get("incomplete")),
        "q4_unrated_bonds": _block({"credit_rating": (conc.get("hidden_risks") or {}).get("credit_rating", "нет данных")}, ready=True, beta=True),
        "q5_full_stress": _block({"reverse": stress.get("reverse"), "scenarios": stress.get("scenarios")}, ready=not stress.get("empty")),
    }
    payload = {
        "source": "portfolio_report",
        "config_version": CONFIG_VERSION,
        "as_of": now,
        "user_id": user_id,
        "mode": mode,
        "empty": empty,
        # Empty book is empty — never label it as a demo fixture (GA16-303).
        "demo": False,
        "headline": headline,
        "queues": queues,
        "returns": returns,
        "risk": {
            "var_95": risk.get("var_95"),
            "es_975": risk.get("es_975"),
            "rubles_var_95": risk.get("rubles_var_95"),
            "var_95_unit": "fraction",
            "rubles_var_95_unit": "RUB",
            "traffic_light": risk.get("traffic_light"),
            "status": risk.get("status"),
        },
        "concentration": conc,
        "stress": stress,
        "behavior": behavior,
        "lawyer_flags": {
            "sandbox": is_enabled("qa_sandbox"),
            "personal_limits": is_enabled("qa_personal_limits"),
            "prefill_order_size": False,
            "qualified_docs": is_enabled("qa_qualified_docs"),
        },
        "elapsed_ms": int((perf_counter() - started) * 1000),
        "disclaimer": "Отчёт собирает числа ядра. Это не прогноз и не указание действовать.",
        "fund": _fund_block(risk, user_id=user_id, mode=mode),
        "first_screen": _first_screen(returns, risk, conc, stress, now, empty),
        "investment_profile": _profile_snapshot(user_id, mode),
        "maneuver_control": _maneuver_control(user_id),
    }
    text = f"{headline} {payload['disclaimer']}"
    if filter_wording(text):
        payload["headline"] = "Сводка портфеля недоступна в этой формулировке."
    with _lock:
        hist = _history.setdefault(f"{user_id}:{mode}", [])
        prev = hist[-1] if hist else None
        payload["changed"] = _diff(prev, payload) if prev else []
        hist.append({"as_of": now, "var_95": payload["risk"]["var_95"], "hhi": conc.get("hhi")})
        payload["history_n"] = len(hist)
    return payload


def _maneuver_control(user_id: str) -> dict[str, Any]:
    if not is_enabled("qa_maneuver_control"):
        return {"status": "off", "items": []}
    from app.services.maneuver_control.service import user_report

    try:
        return user_report(user_id)
    except RuntimeError:
        return {"status": "нет данных", "items": []}


def _fund_block(risk: dict[str, Any], *, user_id: str, mode: str) -> dict[str, Any]:
    if not is_enabled("qa_k6_fund_report"):
        return {"data_status": "off"}
    from app.services.fund_report.metrics import fund_metrics

    out = fund_metrics(risk.get("daily_returns") or [], attribution=risk.get("attribution"))
    out["k1"] = _k1_block(user_id=user_id, mode=mode)
    from app.services.fund_report.islands import attach_islands

    islands = attach_islands(user_id=user_id, mode=mode)
    out["factors"] = islands["factors"]
    out["stress_rate"] = islands["stress_rate"]
    out["futures"] = islands["futures"]
    out["goals"] = islands["goals"]
    out["bonds"] = islands["bonds"]
    out["income"] = islands["income"]
    out["look_through"] = islands["look_through"]
    out["liquidity"] = islands["liquidity"]
    return out


def _k1_block(*, user_id: str, mode: str) -> dict[str, Any]:
    if not is_enabled("qa_k1_benchmark"):
        return {
            "status": "off",
            "data_status": "нет данных",
            "reason": "нет данных",
            "alternatives": [],
        }
    from app.services.benchmark_alt.service import as_dict, compare_simple_alternatives

    try:
        payload = as_dict(compare_simple_alternatives(user_id=user_id, mode=mode, period="inception"))
    except Exception as exc:
        return {
            "status": "нет данных",
            "data_status": "нет данных",
            "reason": "ориентир недоступен",
            "alternatives": [],
            "error_class": type(exc).__name__,
        }
    payload["status"] = payload.get("data_status") or "нет данных"
    return payload


def history(*, user_id: str, mode: str = "paper") -> list[dict[str, Any]]:
    with _lock:
        return list(_history.get(f"{user_id}:{mode}") or [])


def _headline(empty: bool, risk: dict[str, Any], conc: dict[str, Any]) -> str:
    if empty:
        try:
            return render("insufficient", {"n": 0, "min_n": 1})["phrase"]
        except Exception:
            return "Демо-сводка: в книге нет позиций."
    if risk.get("data_status") in {"нет данных", "недостаточно данных"} or risk.get("var_95") is None:
        return "Сводка риска: нет данных для расчёта."
    rub = risk.get("rubles_var_95")
    if rub is None:
        # Never print a unitless VaR fraction as rubles (E46-03).
        return f"VaR 95% (доля) {risk.get('var_95')}; сумма в рублях — нет данных."
    try:
        return render("var", {"var_rub": rub, "method": risk.get("method") or "fhs"})["phrase"]
    except Exception:
        return f"Концентрация HHI {conc.get('hhi') or 'нет данных'}."


def _core_stress(stress: dict[str, Any]) -> dict[str, Any]:
    wanted = {"2020", "2022_feb_mar", "2022_us_rates"}
    rows = [s for s in (stress.get("scenarios") or []) if s.get("id") in wanted]
    return {"scenarios": rows}


def _block(data: Any, *, ready: bool, beta: bool = False) -> dict[str, Any]:
    status = "ready" if ready and not beta else ("beta" if data is not None else "hidden")
    if not ready and not beta:
        status = "beta"
    return {"status": status, "data": data}


def _first_screen(
    returns: dict[str, Any],
    risk: dict[str, Any],
    conc: dict[str, Any],
    stress: dict[str, Any],
    as_of: str,
    empty: bool,
) -> dict[str, Any]:
    weights = conc.get("weights") or {}
    cmap: list[dict[str, Any]] = []
    top = None
    if isinstance(weights, dict) and weights:
        def _w(value: Any) -> float:
            try:
                return float(value)
            except (TypeError, ValueError):
                return 0.0

        ranked = sorted(weights.items(), key=lambda kv: _w(kv[1]), reverse=True)
        cmap = [{"ticker": str(k), "weight": v} for k, v in ranked]
        if ranked:
            top = {"ticker": str(ranked[0][0]), "weight": ranked[0][1]}
    crisis = None
    for row in stress.get("scenarios") or []:
        if row.get("id") in {"2020", "2022_feb_mar"}:
            crisis = row
            break
    equity = equity_vs_benchmark(
        weights=weights if isinstance(weights, dict) else {},
        benchmark_id=str(returns.get("benchmark_id") or ""),
        benchmark_note=str(returns.get("benchmark_note") or ""),
    )
    if empty:
        equity = {
            "data_status": "нет данных",
            "points": [],
            "benchmark_id": equity.get("benchmark_id"),
            "benchmark_note": equity.get("benchmark_note"),
            "reason": "в книге нет позиций",
        }
    return {
        "twr": returns.get("twr"),
        "mwr": returns.get("mwr"),
        "var_95": risk.get("var_95"),
        "rubles_var_95": risk.get("rubles_var_95"),
        "var_95_unit": "fraction",
        "rubles_var_95_unit": "RUB",
        "traffic_light": risk.get("traffic_light"),
        "risk_status": risk.get("status"),
        "hhi": conc.get("hhi"),
        "top_holding": top,
        "concentration_map": cmap,
        "crisis": crisis,
        "equity_vs_benchmark": equity,
        "events_calendar": {
            "data_status": "нет данных",
            "events": [],
            "reason": "нет данных",
        },
        "as_of": as_of,
        "source": "portfolio_report",
        "empty": empty,
        "data_status": "нет данных" if empty else "ok",
    }


def _diff(prev: dict[str, Any], cur: dict[str, Any]) -> list[str]:
    notes = []
    if prev.get("var_95") != cur["risk"].get("var_95"):
        notes.append("изменился VaR")
    if prev.get("hhi") != (cur.get("concentration") or {}).get("hhi"):
        notes.append("изменилась концентрация")
    return notes


def _profile_snapshot(user_id: str, mode: str) -> dict[str, Any]:
    if not is_enabled("qa_investment_profile"):
        return {"data_status": "флаг выключен"}
    from app.services.investment_profile.service import (
        get_profile,
        warnings_vs_portfolio,
    )

    row = get_profile(user_id)
    if row is None:
        return {"data_status": "нет данных", "empty": True}
    return {
        "data_status": "ok",
        "version": row.get("version"),
        "horizon": row.get("horizon"),
        "risk_tolerance": row.get("risk_tolerance"),
        "limits": row.get("limits"),
        "warnings": warnings_vs_portfolio(user_id, mode=mode),
        "source": "investment_profile",
    }
