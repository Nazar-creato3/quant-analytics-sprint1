"""Attach factor / rate / futures / goal conclusions for 60 and K6.

Numbers come only from the owner services. Failures become «нет данных» + reason.
"""
from __future__ import annotations

from typing import Any

from app.services.qa.feature_flags import is_enabled


def attach_islands(*, user_id: str, mode: str) -> dict[str, Any]:
    return {
        "factors": factor_block(user_id=user_id, mode=mode),
        "stress_rate": rate_block(user_id=user_id, mode=mode),
        "futures": futures_block(user_id=user_id, mode=mode),
        "goals": goal_block(user_id=user_id, mode=mode),
        "bonds": bonds_block(user_id=user_id, mode=mode),
        "income": income_block(user_id=user_id, mode=mode),
        "look_through": lookthrough_block(user_id=user_id, mode=mode),
        "liquidity": liquidity_block(user_id=user_id, mode=mode),
    }


def factor_block(*, user_id: str, mode: str) -> dict[str, Any]:
    if not is_enabled("qa_factor_lens"):
        return _off("65", "qa_factor_lens выключен")
    try:
        from app.services.factor_lens.service import explain_portfolio

        data = explain_portfolio(user_id, mode=mode)
    except Exception as exc:
        return _fail("65", exc)
    reason = data.get("reason") or data.get("quality_note") or data.get("sentence") or "нет данных"
    return {
        "status": data.get("data_status") or "нет данных",
        "source": "65 factor_lens.explain_portfolio",
        "reason": reason,
        "sentence": data.get("sentence"),
        "enb": data.get("enb"),
        "enb_min_torsion": data.get("enb_min_torsion"),
        "risk_shares": data.get("risk_shares"),
    }


def rate_block(*, user_id: str, mode: str) -> dict[str, Any]:
    if not is_enabled("qa_key_rate"):
        return _off("63", "qa_key_rate выключен")
    try:
        from app.services.key_rate.service import explain_shift

        data = explain_shift(user_id, mode=mode, shift_bp=100)
    except Exception as exc:
        return _fail("63", exc)
    reason = data.get("reason") or data.get("sentence") or "нет данных"
    return {
        "status": data.get("data_status") or "нет данных",
        "source": "63 key_rate.explain_shift",
        "reason": reason,
        "sentence": data.get("sentence"),
        "shift_bp": data.get("shift_bp"),
        "value_change": data.get("value_change"),
        "income_12m": data.get("income_12m"),
    }


def futures_block(*, user_id: str, mode: str) -> dict[str, Any]:
    if not is_enabled("qa_futures_risk"):
        return _off("58A", "qa_futures_risk выключен")
    try:
        from app.services.futures_risk.service import explain
        from app.services.risk_engine.service import _holdings_from_book, _nav_rub

        holdings = _holdings_from_book(user_id, mode)
        rows = [
            h
            for h in holdings
            if h.get("point_value") is not None and h.get("price") is not None
        ]
        if not rows:
            return {
                "status": "нет данных",
                "source": "58A futures_risk.explain",
                "reason": "в книге нет фьючерсов с ценой и стоимостью пункта",
                "leverage": None,
                "hedge": None,
            }
        nav = _nav_rub(holdings)
        data = explain(positions=rows, liquid_nav=nav)
    except Exception as exc:
        return _fail("58A", exc)
    return {
        "status": data.get("data_status") or "нет данных",
        "source": "58A futures_risk.explain",
        "reason": data.get("reason") or "нет данных",
        "leverage": data.get("leverage"),
        "cushion": data.get("cushion"),
        "hedge": data.get("hedge"),
    }


def goal_block(*, user_id: str, mode: str) -> dict[str, Any]:
    if not is_enabled("qa_goals"):
        return _off("K5", "qa_goals выключен")
    try:
        from app.services.goals.service import explain_goal, last_goal_inputs

        saved = last_goal_inputs(user_id)
        if not saved or saved.get("target_amount") is None or not saved.get("target_date"):
            return {
                "status": "нет данных",
                "source": "K5 goals.explain_goal",
                "reason": "цель не задана",
                "probability": None,
            }
        data = explain_goal(
            user_id,
            target_amount=float(saved["target_amount"]),
            target_date=str(saved["target_date"]),
            monthly_contrib=float(saved.get("monthly_contrib") or 0.0),
            mode=str(saved.get("mode") or mode),
        )
    except Exception as exc:
        return _fail("K5", exc)
    return {
        "status": data.get("data_status") or "нет данных",
        "source": "K5 goals.explain_goal",
        "reason": data.get("reason") or data.get("caption") or "нет данных",
        "probability": data.get("probability"),
        "p05": data.get("p05"),
        "p95": data.get("p95"),
        "caption": data.get("caption"),
        "notify_10pp": data.get("notify_10pp"),
    }


def bonds_block(*, user_id: str, mode: str) -> dict[str, Any]:
    if not is_enabled("qa_bonds"):
        return _off("56", "qa_bonds выключен")
    try:
        from app.services.bonds.service import portfolio_bonds

        data = portfolio_bonds(user_id, mode)
    except Exception as exc:
        return _fail("56", exc)
    if data.get("status") == "flag_off":
        return _off("56", "qa_bonds выключен")
    summary = data.get("summary") or {}
    reason = data.get("reason")
    if not reason:
        if data.get("data_status") == "нет данных":
            reason = "в книге нет облигаций с оценкой"
        elif summary.get("partial"):
            reason = "частично: " + ", ".join(str(x) for x in (summary.get("excluded") or []))
        else:
            reason = f"выпусков {summary.get('count')}"
    return {
        "status": data.get("data_status") or "нет данных",
        "source": "56 bonds.portfolio_bonds",
        "reason": reason,
        "ytm": summary.get("ytm"),
        "duration": summary.get("duration"),
        "count": summary.get("count"),
    }


def income_block(*, user_id: str, mode: str) -> dict[str, Any]:
    if not is_enabled("qa_payouts"):
        return _off("57", "qa_payouts выключен")
    try:
        from app.services.payouts.service import cashflow_summary

        data = cashflow_summary(user_id, mode, months=12)
    except Exception as exc:
        return _fail("57", exc)
    if data.get("status") == "flag_off":
        return _off("57", "qa_payouts выключен")
    declared = data.get("passive_declared_net_12m")
    reason = data.get("reason")
    if not reason:
        if data.get("data_status") == "нет данных":
            reason = "нет событий выплат на горизонте 12 месяцев"
        else:
            reason = f"объявленный нетто 12м {declared}" if declared is not None else "календарь выплат"
    return {
        "status": data.get("data_status") or "нет данных",
        "source": "57 payouts.cashflow_summary",
        "reason": reason,
        "passive_declared_net_12m": declared,
        "by_type": data.get("by_type"),
    }


def lookthrough_block(*, user_id: str, mode: str) -> dict[str, Any]:
    if not is_enabled("qa_fund_lookthrough"):
        return _off("61", "qa_fund_lookthrough выключен")
    try:
        from app.services.fund_lookthrough.service import lookthrough_portfolio

        data = lookthrough_portfolio(user_id, mode=mode, by="issuer", view="lookthrough")
    except Exception as exc:
        return _fail("61", exc)
    reason = data.get("reason")
    rows = data.get("rows") or []
    if not reason:
        if data.get("data_status") == "нет данных":
            reason = "нет сквозных весов"
        elif rows:
            top = rows[0]
            reason = f"крупнейший эмитент {top.get('key')} {top.get('weight')}"
        else:
            reason = "сквозной взгляд без строк"
    return {
        "status": data.get("data_status") or "нет данных",
        "source": "61 fund_lookthrough.lookthrough_portfolio",
        "reason": reason,
        "n_rows": len(rows),
        "hidden_n": len(data.get("hidden") or []),
    }


def liquidity_block(*, user_id: str, mode: str) -> dict[str, Any]:
    if not is_enabled("qa_position_liquidity"):
        return _off("64", "qa_position_liquidity выключен")
    try:
        from app.services.position_liquidity.service import portfolio_liquidity

        data = portfolio_liquidity(user_id, mode, participation=0.1)
    except Exception as exc:
        return _fail("64", exc)
    if data.get("status") == "flag_off":
        return _off("64", "qa_position_liquidity выключен")
    reason = data.get("reason")
    if not reason:
        share = data.get("share_1d")
        reason = (
            f"доля выхода за 1 день {share}"
            if share is not None
            else (data.get("data_status") or "нет данных")
        )
    return {
        "status": data.get("data_status") or "нет данных",
        "source": "64 position_liquidity.portfolio_liquidity",
        "reason": reason,
        "share_1d": data.get("share_1d"),
        "share_5d": data.get("share_5d"),
        "fire_sale_1d_cost_rub": data.get("fire_sale_1d_cost_rub"),
    }


def _off(module: str, _reason: str) -> dict[str, Any]:
    return {"status": "нет данных", "module": module, "reason": "нет данных", "values": None}


def _fail(module: str, exc: Exception) -> dict[str, Any]:
    return {
        "status": "нет данных",
        "module": module,
        "reason": "расчёт недоступен",
        "error_class": type(exc).__name__,
        "values": None,
    }
