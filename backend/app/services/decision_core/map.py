"""Turn a module payload into one signal. No new financial numbers."""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Any

from app.services.explanations.service import filter_wording
from app.services.legal.catalog import load_ui_texts


def texts() -> dict[str, str]:
    raw = load_ui_texts().get("brain") or {}
    return {str(k): str(v) for k, v in raw.items()}


def as_text(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, float):
        if math.isnan(value):
            return None
        return format(value, ".6g")
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped in {"", "нет данных", "None"}:
            return None
        return stripped
    return None


def as_float(value: Any) -> float | None:
    text = as_text(value)
    if text is None:
        return None
    try:
        number = float(text.replace(" ", "").replace(",", "."))
    except ValueError:
        return None
    if math.isnan(number):
        return None
    return number


def _status(payload: dict[str, Any]) -> str:
    raw = payload.get("data_status") or payload.get("status") or ""
    return str(raw)


def _usable(payload: dict[str, Any]) -> bool:
    return _status(payload) in {"ok", "частично"}


def _fill(template: str, values: dict[str, str]) -> str:
    out = template
    for key, value in values.items():
        out = out.replace("{" + key + "}", value)
    return out


def make_signal(
    payload: dict[str, Any],
    *,
    signal_id: str,
    module: str,
    module_label: str,
    source: str,
    href: str,
    methodology: str,
    label: str,
    figure: str,
    scale: float,
) -> dict[str, Any] | None:
    if not _usable(payload):
        return None
    number = as_float(figure)
    if number is None:
        return None
    bundle = texts()
    status = _status(payload)
    confidence = bundle["confidence_ok"] if status == "ok" else bundle["confidence_partial"]
    values = {
        "module": module_label,
        "label": label,
        "figure": figure,
        "source": source,
    }
    why = _fill(bundle["why"], values)
    if_idle = _fill(bundle["if_idle"], values)
    if filter_wording(why) or filter_wording(if_idle) or filter_wording(confidence):
        return None
    importance = min(1.0, abs(number) / scale) if scale else 0.0
    return {
        "signal_id": signal_id,
        "module": module,
        "module_label": module_label,
        "source": source,
        "href": href,
        "methodology": methodology,
        "label": label,
        "figure": figure,
        "why": why,
        "if_idle": if_idle,
        "confidence": confidence,
        "data_status": status,
        "as_of": as_text(payload.get("as_of")),
        "importance": importance,
    }


def from_risk(payload: dict[str, Any]) -> dict[str, Any] | None:
    figure = as_text(payload.get("var_95"))
    if figure is None:
        return None
    return make_signal(
        payload,
        signal_id="risk.var95",
        module="risk_engine",
        module_label="риск",
        source="risk_engine.compute_risk_for_user",
        href="/portfolio-risk",
        methodology="/methodology/risk",
        label="VaR 95",
        figure=figure,
        scale=0.2,
    )


def from_k6(payload: dict[str, Any]) -> dict[str, Any] | None:
    figure = as_text(payload.get("max_dd"))
    if figure is None:
        return None
    return make_signal(
        payload,
        signal_id="k6.max_dd",
        module="fund_report",
        module_label="K6",
        source="fund_report.fund_metrics",
        href="/portfolio-report",
        methodology="/methodology/risk",
        label="просадка",
        figure=figure,
        scale=0.2,
    )


def from_k1(payload: dict[str, Any]) -> dict[str, Any] | None:
    alts = payload.get("alternatives") or []
    figure = None
    if alts and isinstance(alts[0], dict):
        figure = as_text(alts[0].get("diff_twr_pp"))
    if figure is None:
        return None
    return make_signal(
        payload,
        signal_id="k1.diff_twr_pp",
        module="benchmark_alt",
        module_label="K1",
        source="benchmark_alt.compare_simple_alternatives",
        href="/portfolio-report",
        methodology="/methodology/k1-simple-alternative",
        label="разница TWR к альтернативе, п.п.",
        figure=figure,
        scale=5.0,
    )


def from_decisions(payload: dict[str, Any]) -> dict[str, Any] | None:
    figure = as_text(payload.get("total_rubles"))
    if figure is None:
        return None
    return make_signal(
        payload,
        signal_id="d59.total_rubles",
        module="decisions_report",
        module_label="59",
        source="decisions_report.analyze_decisions",
        href="/decisions",
        methodology="/methodology/decisions",
        label="цена решений, ₽",
        figure=figure,
        scale=100_000.0,
    )


def from_costs(payload: dict[str, Any]) -> dict[str, Any] | None:
    figure = as_text(payload.get("total_rubles"))
    if figure is None:
        return None
    return make_signal(
        payload,
        signal_id="d62.total_rubles",
        module="total_costs",
        module_label="62",
        source="total_costs.analyze_costs",
        href="/costs",
        methodology="/methodology/costs",
        label="комиссии, ₽",
        figure=figure,
        scale=100_000.0,
    )


def from_pretrade(payload: dict[str, Any]) -> dict[str, Any] | None:
    if not payload.get("trades"):
        return None
    before = (payload.get("before") or {}).get("var_95")
    after = (payload.get("after") or {}).get("var_95")
    b = as_float(before)
    a = as_float(after)
    if b is None or a is None:
        return None
    figure = as_text(a - b)
    if figure is None:
        return None
    return make_signal(
        payload,
        signal_id="d60.var_delta",
        module="pretrade_check",
        module_label="60",
        source="pretrade_check.check_basket",
        href="/pretrade",
        methodology="/methodology/pretrade",
        label="изменение VaR 95 по корзине",
        figure=figure,
        scale=0.05,
    )


def from_bonds(payload: dict[str, Any]) -> dict[str, Any] | None:
    summary = payload.get("summary") or {}
    figure = as_text(summary.get("duration"))
    if figure is None or _status(payload) == "flag_off":
        return None
    body = dict(payload)
    if body.get("data_status") not in {"ok", "частично"}:
        return None
    return make_signal(
        body,
        signal_id="d56.duration",
        module="bonds",
        module_label="56",
        source="bonds.portfolio_bonds",
        href="/portfolio-bonds",
        methodology="/methodology/bonds",
        label="дюрация, лет",
        figure=figure,
        scale=5.0,
    )


def from_payouts(payload: dict[str, Any]) -> dict[str, Any] | None:
    figure = as_text(payload.get("passive_declared_net_12m"))
    if figure is None or payload.get("status") == "flag_off":
        return None
    body = dict(payload)
    if body.get("data_status") not in {"ok", "частично"}:
        return None
    return make_signal(
        body,
        signal_id="d57.net_12m",
        module="payouts",
        module_label="57",
        source="payouts.cashflow_summary",
        href="/payout-calendar",
        methodology="/methodology/payouts",
        label="объявленные выплаты за 12 месяцев, ₽",
        figure=figure,
        scale=100_000.0,
    )


def from_liquidity(payload: dict[str, Any]) -> dict[str, Any] | None:
    figure = as_text(payload.get("share_1d"))
    if figure is None or payload.get("status") == "flag_off":
        return None
    body = dict(payload)
    if body.get("data_status") not in {"ok", "частично"}:
        return None
    return make_signal(
        body,
        signal_id="d64.share_1d",
        module="position_liquidity",
        module_label="64",
        source="position_liquidity.portfolio_liquidity",
        href="/liquidity",
        methodology="/methodology/liquidity",
        label="доля, которую расчёт выводит за 1 день",
        figure=figure,
        scale=1.0,
    )


def from_lookthrough(payload: dict[str, Any]) -> dict[str, Any] | None:
    rows = payload.get("rows") or []
    best: str | None = None
    best_abs = -1.0
    for row in rows:
        if not isinstance(row, dict):
            continue
        text = as_text(row.get("weight"))
        number = as_float(text)
        if text is None or number is None:
            continue
        if abs(number) > best_abs:
            best_abs = abs(number)
            best = text
    if best is None:
        return None
    return make_signal(
        payload,
        signal_id="d61.top_weight",
        module="fund_lookthrough",
        module_label="61",
        source="fund_lookthrough.lookthrough_portfolio",
        href="/portfolio-structure",
        methodology="/methodology/fund-look-through",
        label="крупнейший сквозной вес",
        figure=best,
        scale=0.25,
    )


def from_tax(payload: dict[str, Any]) -> dict[str, Any] | None:
    year = payload.get("year") or {}
    if not isinstance(year, dict) or year.get("status") == "нет данных":
        return None
    figure = as_text(year.get("tax_cash"))
    if figure is None:
        return None
    return make_signal(
        payload,
        signal_id="k3.tax_cash",
        module="tax_ru",
        module_label="K3",
        source="tax_ru.explain_tax",
        href="/tax",
        methodology="/methodology/tax",
        label="оценка налога за год, ₽",
        figure=figure,
        scale=100_000.0,
    )


def from_factors(payload: dict[str, Any]) -> dict[str, Any] | None:
    figure = as_text(payload.get("enb"))
    if figure is None:
        return None
    body = dict(payload)
    quality = str(payload.get("quality") or "")
    if body.get("data_status") not in {"ok", "частично"}:
        body["data_status"] = quality if quality in {"ok", "частично"} else "нет данных"
    return make_signal(
        body,
        signal_id="d65.enb",
        module="factor_lens",
        module_label="65",
        source="factor_lens.explain_portfolio",
        href="/factors",
        methodology="/methodology/factor-lens",
        label="эффективное число независимых ставок",
        figure=figure,
        scale=5.0,
    )


def from_key_rate(payload: dict[str, Any]) -> dict[str, Any] | None:
    figure = as_text(payload.get("value_change"))
    if figure is None:
        return None
    return make_signal(
        payload,
        signal_id="d63.value_change",
        module="key_rate",
        module_label="63",
        source="key_rate.explain_shift",
        href="/key-rate",
        methodology="/methodology/key-rate",
        label="изменение стоимости при сдвиге ставки, ₽",
        figure=figure,
        scale=100_000.0,
    )


def from_futures(payload: dict[str, Any]) -> dict[str, Any] | None:
    figure = as_text(payload.get("leverage"))
    if figure is None:
        return None
    return make_signal(
        payload,
        signal_id="d58a.leverage",
        module="futures_risk",
        module_label="58A",
        source="futures_risk.explain",
        href="/futures-risk",
        methodology="/methodology/futures",
        label="плечо",
        figure=figure,
        scale=2.0,
    )


def from_futures_market(payload: dict[str, Any]) -> dict[str, Any] | None:
    profile = payload.get("profile") or {}
    figure = as_text(profile.get("poc")) if isinstance(profile, dict) else None
    if figure is None:
        return None
    return make_signal(
        payload,
        signal_id="d58b.poc",
        module="futures_market",
        module_label="58B",
        source="futures_market.explain_market",
        href="/futures-market",
        methodology="/methodology/futures-market",
        label="цена наибольшего объёма",
        figure=figure,
        scale=100_000.0,
    )


def from_goal(payload: dict[str, Any]) -> dict[str, Any] | None:
    figure = as_text(payload.get("probability"))
    if figure is None:
        return None
    return make_signal(
        payload,
        signal_id="k5.probability",
        module="goals",
        module_label="K5",
        source="goals.explain_goal",
        href="/goals",
        methodology="/methodology/goals",
        label="вероятность цели по прошлым данным",
        figure=figure,
        scale=1.0,
    )


MAPPERS = {
    "risk": from_risk,
    "k6": from_k6,
    "k1": from_k1,
    "d59": from_decisions,
    "d62": from_costs,
    "d60": from_pretrade,
    "d56": from_bonds,
    "d57": from_payouts,
    "d64": from_liquidity,
    "d61": from_lookthrough,
    "k3": from_tax,
    "d65": from_factors,
    "d63": from_key_rate,
    "d58a": from_futures,
    "d58b": from_futures_market,
    "k5": from_goal,
}
