"""Stress library + factor sensitivities (Prompt 13).

Numbers are Decimal for money, float for returns. Stress is vulnerability, not a forecast.
"""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from threading import Lock
from typing import Any

from app.services.market_analysis.scenarios import apply_factor_shock
from app.services.portfolio_book.store import get_book
from app.services.qa.feature_flags import is_enabled
from app.services.qa.shadow_mode import record_diff
from app.services.risk_engine.series import get_series

CONFIG_VERSION = "stress_library.v1"
FACTORS = ("market", "oil", "rub", "rate", "credit_spread", "sector")
FACTOR_TICKERS = {
    "market": "IMOEX",
    "oil": "BRENT",
    "rub": "USDRUB",
    "rate": "KEYRATE",
    "sector": "SECTOR",
}
DISCLAIMER = "Стресс-тест показывает уязвимость портфеля, не прогноз доходности."

_lock = Lock()
_cache: dict[str, dict[str, Any]] = {}
_exposures: dict[str, dict[str, Any]] = {}


def _reset() -> None:
    with _lock:
        _cache.clear()
        _exposures.clear()


def load_catalog() -> dict[str, Any]:
    return json.loads((Path(__file__).with_name("scenarios.json")).read_text(encoding="utf-8"))


def list_scenarios() -> list[dict[str, Any]]:
    cat = load_catalog()
    rows = []
    for kind in ("historical", "hypothetical"):
        for item in cat[kind]:
            rows.append({**item, "kind": kind, "config_version": CONFIG_VERSION})
    return rows


def _ols_beta(y: list[float], x: list[float]) -> tuple[float | None, float, int]:
    n = min(len(y), len(x))
    if n < 20:
        return None, 0.0, n
    yy, xx = y[-n:], x[-n:]
    mx = sum(xx) / n
    my = sum(yy) / n
    varx = sum((a - mx) ** 2 for a in xx)
    if varx <= 1e-18:
        return None, 0.0, n
    cov = sum((a - mx) * (b - my) for a, b in zip(xx, yy))
    beta = cov / varx
    resid = [b - (my - beta * mx) - beta * a for a, b in zip(xx, yy)]
    ssr = sum(r * r for r in resid)
    sst = sum((b - my) ** 2 for b in yy)
    r2 = 1.0 - ssr / sst if sst > 1e-18 else 0.0
    return float(beta), float(max(0.0, min(1.0, r2))), n


def estimate_exposures(ticker: str, *, as_of: date | None = None) -> dict[str, Any]:
    y = get_series(ticker)
    betas: dict[str, float | None] = {}
    quality = "ok"
    reasons: list[str] = []
    r2_max = 0.0
    n_used = 0
    for name, fticker in FACTOR_TICKERS.items():
        x = get_series(fticker)
        beta, r2, n = _ols_beta(y, x)
        betas[name] = beta
        n_used = max(n_used, n)
        r2_max = max(r2_max, r2)
        if beta is None:
            reasons.append(f"{name}: мало перекрытия с {fticker}")
    if ticker.upper().startswith("OFZ") or ticker.upper().endswith("BOND"):
        # Duration is never invented: without a series it stays unset.
        betas["duration"] = None
        if betas.get("credit_spread") is None:
            betas["credit_spread"] = None
            reasons.append("нет дюрации и спреда без ряда облигации")
    else:
        betas["duration"] = None
    if n_used < 40 or r2_max < 0.10:
        quality = "limited"
        reasons.append("оценка чувствительности слабая (n<40 или R²<0.1)")
    if not y:
        quality = "no_history"
        reasons.append("нет ряда бумаги")
        betas["duration"] = None
        betas["credit_spread"] = None
    row = {
        "ticker": ticker.upper(),
        "as_of": (as_of or date.today()).isoformat(),
        "betas": betas,
        "quality": quality,
        "n": n_used,
        "r2": r2_max,
        "reasons": reasons,
        "source": "stress_library",
    }
    with _lock:
        _exposures[ticker.upper()] = row
    return row


def _ret_from_factors(exp: dict[str, Any], shocks: dict[str, float]) -> float:
    betas = exp.get("betas") or {}
    total = 0.0
    for name, shock in shocks.items():
        if name == "rate" and betas.get("duration") is not None:
            total += -float(betas["duration"]) * float(shock)
            continue
        b = betas.get(name)
        if b is None:
            continue
        total += float(b) * float(shock)
    return total


def _position_return(ticker: str, scenario: dict[str, Any], history: list[float] | None) -> dict[str, Any]:
    exp = estimate_exposures(ticker)
    shocks = dict(scenario.get("shocks") or {})
    if history and len(history) >= 2 and not scenario.get("id") == "1987":
        actual = 1.0
        for r in history:
            actual *= 1.0 + float(r)
        actual -= 1.0
        return {
            "ticker": ticker,
            "ret": actual,
            "method": "actual_history",
            "quality": "ok",
            "exposures": exp,
        }
    ret = _ret_from_factors(exp, shocks)
    quality = "limited" if exp["quality"] != "ok" or scenario.get("limited_accuracy") else "ok"
    return {
        "ticker": ticker,
        "ret": ret,
        "method": "factor_proxy",
        "quality": quality,
        "exposures": exp,
        "reason": scenario.get("reason") or "; ".join(exp.get("reasons") or []),
    }


def _holdings_from_book(user_id: str, mode: str) -> list[dict[str, Any]]:
    from app.services.concentration.service import _trade_price

    rows = get_book().positions(user_id=user_id, mode=mode)  # type: ignore[arg-type]
    out = []
    for p in rows:
        if p.ticker.upper() == "CASH":
            continue
        px = _trade_price(user_id, mode, p.ticker)
        if px is None:
            continue
        out.append({"ticker": p.ticker, "value": abs(float(p.qty)) * float(px), "ccy": p.ccy})
    return out


def run_holdings(
    holdings: list[dict[str, Any]],
    *,
    actual_history: dict[str, list[float]] | None = None,
) -> dict[str, Any]:
    if not is_enabled("qa_stress_library"):
        raise RuntimeError("qa_stress_library off")
    cat = load_catalog()
    if not holdings:
        return {
            "disclaimer": DISCLAIMER,
            "config_version": CONFIG_VERSION,
            "nav": None,
            "ccy": "RUB",
            "scenarios": [],
            "reverse": [],
            "source": "stress_library",
            "empty": True,
            "data_status": "нет данных",
            "status": "insufficient_data",
            "reason": "пустая книга или нет цен позиций",
        }
    total_value, nav_ccy, ccy_reason = _nav_one_currency(holdings)
    if ccy_reason:
        return {
            "disclaimer": DISCLAIMER,
            "config_version": CONFIG_VERSION,
            "nav": None,
            "ccy": None,
            "scenarios": [],
            "reverse": [],
            "source": "stress_library",
            "empty": True,
            "data_status": "нет данных",
            "status": "insufficient_data",
            "reason": ccy_reason,
        }
    if total_value is None or total_value <= 0:
        return {
            "disclaimer": DISCLAIMER,
            "config_version": CONFIG_VERSION,
            "nav": None,
            "ccy": nav_ccy or "RUB",
            "scenarios": [],
            "reverse": [],
            "source": "stress_library",
            "empty": True,
            "data_status": "нет данных",
            "status": "insufficient_data",
            "reason": "сумма стоимостей позиций неположительна",
        }
    scenarios: list[dict[str, Any]] = []
    for kind in ("historical", "hypothetical"):
        for item in cat[kind]:
            contrib: list[dict[str, Any]] = []
            pnl = 0.0
            limited = bool(item.get("limited_accuracy"))
            methods: set[str] = set()
            for h in holdings:
                hist = (actual_history or {}).get(str(h["ticker"]).upper())
                row = _position_return(str(h["ticker"]), item, hist)
                w = float(h["value"]) / total_value
                loss = w * float(row["ret"])
                if item.get("id") == "sanctions_block":
                    loss -= w * float(item.get("blocked_share") or 0.0)
                    row["method"] = "factor_proxy_plus_block"
                    limited = True
                if item.get("id") == "halt_month":
                    # Illiquid ≠ zero loss: keep computed return; do not invent 0 PnL.
                    row["method"] = "last_price_illiquid"
                    row["reason"] = item.get("assumption")
                    limited = True
                    if hist is None and abs(float(row.get("ret") or 0.0)) < 1e-15:
                        row["quality"] = "no_data"
                        row["ret"] = None
                        loss = None  # type: ignore[assignment]
                if loss is None:
                    limited = True
                    methods.add(str(row["method"]))
                    contrib.append(
                        {
                            **row,
                            "weight": w,
                            "pnl_pct": None,
                            "value": h["value"],
                            "ccy": h.get("ccy", "RUB"),
                        }
                    )
                    continue
                pnl += loss
                methods.add(str(row["method"]))
                if row["quality"] != "ok":
                    limited = True
                contrib.append({**row, "weight": w, "pnl_pct": loss, "value": h["value"], "ccy": h.get("ccy", nav_ccy)})
            known = [c for c in contrib if c.get("pnl_pct") is not None]
            if item.get("id") == "halt_month" and not known:
                pnl_out: float | None = None
                pnl_money = None
                limited = True
            else:
                pnl_out = pnl
                pnl_money = money(pnl * total_value)
            scenarios.append(
                {
                    "id": item["id"],
                    "title": item["title"],
                    "kind": kind,
                    "pnl_pct": pnl_out,
                    "pnl_money": pnl_money,
                    "pnl_rub": pnl_money if nav_ccy == "RUB" else None,
                    "ccy": nav_ccy,
                    "limited_accuracy": limited,
                    "reason": item.get("reason") or item.get("assumption") or "",
                    "source": item.get("source"),
                    "method": "+".join(sorted(methods)),
                    "contributions": contrib,
                    "disclaimer": DISCLAIMER,
                }
            )
    reverse = reverse_stress(holdings, targets=(-0.20, -0.30))
    payload = {
        "disclaimer": DISCLAIMER,
        "config_version": CONFIG_VERSION,
        "nav": total_value,
        "ccy": nav_ccy,
        "scenarios": scenarios,
        "reverse": reverse,
        "source": "stress_library",
        "empty": False,
        "data_status": "ok",
    }
    _shadow_legacy(holdings, scenarios)
    return payload


def run_portfolio(*, user_id: str, mode: str = "paper") -> dict[str, Any]:
    key = f"{user_id}:{mode}:{CONFIG_VERSION}"
    with _lock:
        cached = _cache.get(key)
        if cached:
            return cached
    payload = run_holdings(_holdings_from_book(user_id, mode))
    try:
        from app.services.bonds.service import attach_to_stress_library

        payload = attach_to_stress_library(payload, user_id)
    except Exception:
        payload = dict(payload)
        payload["bond_rate_stress_status"] = "нет данных"
    with _lock:
        _cache[key] = payload
    return payload


def _nav_one_currency(
    holdings: list[dict[str, Any]],
) -> tuple[float | None, str | None, str | None]:
    """Sum values only within one currency. Mixed CCYs without FX → нет данных."""
    ccys = {str(h.get("ccy") or "RUB").upper() for h in holdings}
    if len(ccys) > 1:
        return None, None, "разные валюты без курса — суммы в одну валюту нет"
    ccy = next(iter(ccys)) if ccys else "RUB"
    total = sum(float(h["value"]) for h in holdings)
    return total, ccy, None


def reverse_stress(holdings: list[dict[str, Any]], targets: tuple[float, ...] = (-0.20, -0.30)) -> list[dict[str, Any]]:
    """Minimal market shock that reaches a loss target (other factors at 0)."""
    if not holdings:
        return [
            {
                "target_pnl_pct": tgt,
                "market_shock": None,
                "explain": "нет данных: пустая книга",
                "quality": "no_data",
            }
            for tgt in targets
        ]
    total, _ccy, ccy_reason = _nav_one_currency(holdings)
    if ccy_reason:
        return [
            {
                "target_pnl_pct": tgt,
                "market_shock": None,
                "explain": f"нет данных: {ccy_reason}",
                "quality": "no_data",
            }
            for tgt in targets
        ]
    if total is None or total <= 0:
        return [
            {
                "target_pnl_pct": tgt,
                "market_shock": None,
                "explain": "нет данных: стоимость портфеля неизвестна",
                "quality": "no_data",
            }
            for tgt in targets
        ]
    port_beta = 0.0
    for h in holdings:
        exp = estimate_exposures(str(h["ticker"]))
        b = exp["betas"].get("market")
        if b is None:
            continue
        port_beta += float(b) * (float(h["value"]) / total)
    rows = []
    for tgt in targets:
        if abs(port_beta) < 1e-9:
            rows.append(
                {
                    "target_pnl_pct": tgt,
                    "market_shock": None,
                    "explain": "Рыночная бета портфеля не оценена — обратный стресс недоступен.",
                    "quality": "limited",
                }
            )
            continue
        shock = tgt / port_beta
        rows.append(
            {
                "target_pnl_pct": tgt,
                "market_shock": shock,
                "portfolio_market_beta": port_beta,
                "explain": (
                    f"Чтобы портфель потерял {abs(tgt):.0%}, рыночный фактор должен сдвинуться "
                    f"примерно на {shock:.1%} при текущей бете {port_beta:.2f}."
                ),
                "quality": "ok",
            }
        )
    return rows


def _shadow_legacy(holdings: list[dict[str, Any]], scenarios: list[dict[str, Any]]) -> None:
    if not holdings:
        return
    exp = {"market_beta": 1.0}
    old_2020 = apply_factor_shock(exp, {"market_beta": -0.34})
    old_2022 = apply_factor_shock(exp, {"market_beta": -0.19})
    new_2020 = next((s["pnl_pct"] for s in scenarios if s["id"] == "2020"), None)
    new_2022 = next((s["pnl_pct"] for s in scenarios if s["id"] == "2022_us_rates"), None)
    record_diff(
        "stress",
        {"old_2020": old_2020, "old_2022": old_2022},
        {"legacy_2020": old_2020, "legacy_2022": old_2022},
        {"new_2020": new_2020, "new_2022": new_2022},
        path=Path(__file__).resolve().parents[3] / "data" / "stress_shadow" / "compare.jsonl",
    )


def money(value: float) -> str:
    return str(Decimal(str(round(value, 2))).quantize(Decimal("0.01")))
