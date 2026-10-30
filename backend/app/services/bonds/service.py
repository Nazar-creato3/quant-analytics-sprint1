"""Portfolio bond tab, issue card, rate stress. Numbers from analytics, texts from legal yaml."""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from typing import Any

from app.services.bonds import ingest, store
from app.services.bonds.analytics import metrics_from_flows, quantlib_available, rate_stress
from app.services.portfolio_book.service import positions_for
from app.services.qa.feature_flags import is_enabled
from app.services.tax_ru.rates import coupon_ndfl_rate

FIXTURE = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "bonds" / "universe.json"
G_SPREAD_WARN = 0.05
METHOD_PATH = "/methodology/bonds"
USER_SOURCE = "данные брокера"
_FLOW_RU = {
    "coupon": "купон",
    "redemption": "погашение",
    "amort": "амортизация",
    "put": "оферта",
    "coupon_plus_redemption": "купон и погашение",
    "coupon_plus_amort": "купон и амортизация",
    "coupon_plus_put": "купон и оферта",
}


def _universe() -> dict[str, Any]:
    if not FIXTURE.is_file():
        return {"settlement": date.today().isoformat(), "references": [], "g_curve": []}
    if not store.all_refs():
        ingest.load_fixture_universe(json.loads(FIXTURE.read_text(encoding="utf-8")))
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def ensure_fixtures() -> None:
    ingest.ensure_fixtures()


def _settlement() -> date:
    return date.fromisoformat(str(_universe()["settlement"]))


def _metrics_for(ref: dict[str, Any], *, to_offer: bool = False) -> dict[str, Any]:
    settlement = date.fromisoformat(ref["settlement"]) if ref.get("settlement") else _settlement()
    flows = ref.get("cashflows_to_offer") if to_offer and ref.get("cashflows_to_offer") else ref.get("cashflows") or []
    if flows:
        dates = [date.fromisoformat(str(r["on_date"])[:10]) for r in flows]
        amts = [float(r["amount_per_bond"]) for r in flows]
    else:
        dates, amts, _ = store.future_cashflows(str(ref["figi"]), settlement)
    dirty = ref.get("dirty_price")
    if dirty is None:
        return {"status": "нет данных", "reason": "нет грязной цены"}
    return metrics_from_flows(
        settlement=settlement,
        flow_dates=dates,
        amounts=amts,
        dirty_price=float(dirty),
        clean_price=None if ref.get("clean_price") is None else float(ref["clean_price"]),
        aci=None if ref.get("aci") is None else float(ref["aci"]),
        annual_coupon=None if ref.get("annual_coupon") is None else float(ref["annual_coupon"]),
        curve_points=store.curve_points(),
        floater=bool(ref.get("floater")),
        next_reset=date.fromisoformat(ref["next_reset"]) if ref.get("next_reset") else None,
        to_offer=to_offer,
    )


def _warnings(ref: dict[str, Any], metrics: dict[str, Any]) -> list[str]:
    out: list[str] = []
    if ref.get("qualified_only"):
        out.append("только для квалифицированных инвесторов")
    if str(ref.get("risk_level") or "") == "high":
        out.append("высокий risk_level по данным брокера")
    gs = metrics.get("g_spread")
    if gs is not None and gs > G_SPREAD_WARN:
        out.append(f"спред выше {G_SPREAD_WARN * 100:.0f} п.п.")
    if ref.get("inflation_linked"):
        out.append("ОФЗ-ИН: номинал индексируется по ИПЦ")
    return out


def _issue_row(ref: dict[str, Any], qty: Decimal) -> dict[str, Any]:
    _ = quantlib_available()
    m_ytm = _metrics_for(ref, to_offer=False)
    m_ytp = _metrics_for(ref, to_offer=True) if ref.get("offer_kind") == "put" else None
    missing = m_ytm.get("status") != "ok"
    dirty = ref.get("dirty_price")
    value = None if dirty is None or missing else float(qty) * float(dirty)
    coupon = ref.get("annual_coupon")
    gross = None if coupon is None else float(qty) * float(coupon)
    ndfl = coupon_ndfl_rate()
    rate = Decimal(str(ndfl["rate"]))
    net = None if gross is None else gross * float(1 - rate)
    return {
        "figi": ref["figi"],
        "secid": ref.get("secid"),
        "name": ref.get("name"),
        "qty": str(qty),
        "ytm": None if missing else m_ytm.get("ytm"),
        "ytp": None if not m_ytp or m_ytp.get("status") != "ok" else m_ytp.get("ytm"),
        "current_yield": None if missing else m_ytm.get("current_yield"),
        "duration": None if missing else m_ytm.get("macaulay"),
        "modified": None if missing else m_ytm.get("modified"),
        "convexity": None if missing else m_ytm.get("convexity"),
        "g_spread": None if missing else m_ytm.get("g_spread"),
        "g_spread_label": "премия за риск относительно гособлигаций",
        "dirty_price": dirty,
        "clean_price": ref.get("clean_price"),
        "aci": ref.get("aci"),
        "value_rub": value,
        "next_event": ref.get("next_event"),
        "floater": bool(ref.get("floater")),
        "inflation_linked": bool(ref.get("inflation_linked")),
        "qualified_only": bool(ref.get("qualified_only")),
        "warnings": [] if missing else _warnings(ref, m_ytm),
        "excluded": missing,
        "status": "нет данных" if missing else "ok",
        "coupon_gross": gross,
        "coupon_net": net,
        "ndfl_rate": str(rate),
        "ndfl_note": ndfl.get("note"),
        "source": USER_SOURCE,
        "as_of": ref.get("as_of") or _universe().get("as_of"),
        "methodology": METHOD_PATH,
        "metrics": _metrics_for_user(m_ytm),
        "offer_metrics": _metrics_for_user(m_ytp),
        "cashflows": _flows_for_user(ref.get("cashflows") or []),
        "_flows": ref.get("cashflows") or [],
    }


def _metrics_for_user(metrics: dict[str, Any] | None) -> dict[str, Any] | None:
    if not metrics:
        return metrics
    hidden = {"engine", "quantlib", "day_count"}
    return {key: value for key, value in metrics.items() if key not in hidden}


def _flows_for_user(flows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    public = []
    for cf in flows:
        kind = str(cf.get("type") or "")
        public.append(
            {
                "on_date": cf.get("on_date"),
                "amount_per_bond": cf.get("amount_per_bond"),
                "type_label": _FLOW_RU.get(kind, "выплата"),
            }
        )
    return public


def _ladder(rows: list[dict[str, Any]]) -> dict[str, Any]:
    buckets: dict[str, float] = {}
    bond_nav = sum(float(r["value_rub"]) for r in rows if r.get("value_rub") is not None)
    for row in rows:
        qty = float(Decimal(str(row["qty"])))
        for cf in row.get("_flows") or []:
            if cf.get("type") not in {"coupon_plus_redemption", "coupon_plus_amort", "coupon_plus_put", "redemption", "amort", "put"}:
                continue
            on = str(cf["on_date"])[:10]
            year = on[:4]
            month = int(on[5:7])
            q = f"{year}Q{(month - 1) // 3 + 1}"
            buckets[q] = buckets.get(q, 0.0) + qty * float(cf["amount_per_bond"])
    hot = []
    if bond_nav > 0:
        for q, amt in buckets.items():
            if amt / bond_nav > 0.30:
                hot.append(q)
    return {"quarters": buckets, "concentration": hot, "threshold": 0.30, "bond_nav": bond_nav}


def _demo_qty(user_id: str, figi: str, ref: dict[str, Any]) -> Decimal:
    try:
        for pos in positions_for(user_id=user_id, mode="paper"):
            if pos.ticker.upper() == figi.upper() and pos.qty > 0:
                return pos.qty
    except Exception:
        pass
    return Decimal("0")


def _iss_refs(user_id: str) -> dict[str, dict[str, Any]]:
    """Bond references for the user's own bonds from the MOEX price-history store."""
    from app.services.price_history import service as history
    from app.services.price_history import store as ph

    out: dict[str, dict[str, Any]] = {}
    today = date.today()
    for pos in positions_for(user_id=user_id, mode="paper"):
        ticker = (pos.ticker or "").upper()
        meta = history.info(ticker)
        if meta.get("market") != "bonds":
            continue
        face = float(meta.get("facevalue") or 1000)
        clean_pct = meta.get("clean_pct")
        aci = float(meta.get("aci") or 0.0)
        clean = None if clean_pct in (None, "") else float(clean_pct) * face / 100.0
        pay = ph.read(f"PAY_{ticker}") or {}
        coupons = [c for c in pay.get("coupons") or [] if str(c["date"]) > today.isoformat()]
        amort = {a["date"]: float(a["amount"]) for a in pay.get("amortizations") or [] if str(a["date"]) > today.isoformat()}
        last_amt = next((c["amount"] for c in reversed(pay.get("coupons") or []) if c.get("amount") is not None), None)
        floater = any(c.get("amount") is None for c in coupons)
        flows = []
        dates = sorted({*(c["date"] for c in coupons), *amort})
        for i, d in enumerate(dates):
            cpn = next((c for c in coupons if c["date"] == d), None)
            amount = (cpn.get("amount") if cpn and cpn.get("amount") is not None else (last_amt if cpn else 0.0)) or 0.0
            principal = amort.get(d, 0.0)
            kind = "coupon"
            if principal:
                kind = "coupon_plus_redemption" if i == len(dates) - 1 else "coupon_plus_amort"
            flows.append({"on_date": d, "amount_per_bond": float(amount) + principal, "type": kind,
                          "status": "known" if cpn is None or cpn.get("amount") is not None else "estimated"})
        if flows and not any(f["type"].startswith("coupon_plus") for f in flows) and meta.get("matdate"):
            flows[-1]["amount_per_bond"] += face  # redemption at maturity when ISS lists no amortisation
            flows[-1]["type"] = "coupon_plus_redemption"
        annual = sum(float(c["amount"] or last_amt or 0) for c in coupons if str(c["date"]) <= (today.replace(year=today.year + 1)).isoformat())
        out[ticker] = {
            "figi": ticker,
            "secid": ticker,
            "name": meta.get("name") or ticker,
            "settlement": today.isoformat(),
            "clean_price": clean,
            "aci": aci,
            "dirty_price": None if clean is None else clean + aci,
            "annual_coupon": annual or None,
            "cashflows": flows,
            "floater": floater,
            "inflation_linked": ticker.startswith("SU52"),
            "next_event": flows[0]["on_date"] if flows else None,
            "as_of": (history.last(ticker) or (today, 0))[0].isoformat(),
        }
    return out


def portfolio_bonds(user_id: str, portfolio_id: str) -> dict[str, Any]:
    if not is_enabled("qa_bonds"):
        return {"status": "flag_off"}
    from app.services.price_history import store as ph

    real = ph.enabled()
    if not real:
        ensure_fixtures()
    issues = []
    excluded = []
    refs = _iss_refs(user_id) if real else store.all_refs()
    for figi, ref in refs.items():
        qty = _demo_qty(user_id, figi, ref)
        if qty <= 0:
            continue
        row = _issue_row(ref, qty)
        row["portfolio_id"] = portfolio_id
        if row["excluded"]:
            excluded.append(figi)
        issues.append(row)
    valued = [r for r in issues if r.get("value_rub") is not None]
    nav = sum(float(r["value_rub"]) for r in valued)
    w_ytm = None
    w_dur = None
    if nav > 0:
        w_ytm = sum(float(r["ytm"]) * float(r["value_rub"]) for r in valued if r.get("ytm") is not None) / nav
        w_dur = sum(float(r["duration"]) * float(r["value_rub"]) for r in valued if r.get("duration") is not None) / nav
    ladder = _ladder(issues)
    for row in issues:
        row.pop("_flows", None)
    return {
        "portfolio_id": portfolio_id,
        "user_id": user_id,
        "as_of": date.today().isoformat() if real else _universe().get("as_of"),
        "source": "Московская биржа" if real else USER_SOURCE,
        "methodology": METHOD_PATH,
        "summary": {
            "nav_rub": nav if valued else None,
            "ytm": w_ytm,
            "duration": w_dur,
            "count": len(valued),
            "excluded": excluded,
            "partial": bool(excluded),
            "partial_label": "частично" if excluded else None,
        },
        "issues": issues,
        "ladder": ladder,
        "curve_as_of": store.curve_as_of(),
        "texts_key": "bonds",
        "data_status": "нет данных" if not issues else ("частично" if excluded else "ok"),
    }


def bond_card(figi: str) -> dict[str, Any]:
    if not is_enabled("qa_bonds"):
        return {"status": "flag_off"}
    ensure_fixtures()
    ref = store.get_reference(figi)
    if ref is None:
        return {"figi": figi, "status": "нет данных", "methodology": METHOD_PATH}
    row = _issue_row(ref, Decimal("1"))
    row.pop("_flows", None)
    row["events"] = [
        {key: value for key, value in ev.items() if key != "source"} for ev in store.get_events(figi)
    ]
    return row


def portfolio_bond_stress(user_id: str, portfolio_id: str, shift_bp: int = 100) -> dict[str, Any]:
    started = perf_counter()
    book = portfolio_bonds(user_id, portfolio_id)
    if book.get("status") == "flag_off":
        return book
    dy = shift_bp / 10_000.0
    rows = []
    total = 0.0
    floater_total = 0.0
    nav = float(book["summary"]["nav_rub"] or 0)
    for issue in book.get("issues") or []:
        if issue.get("excluded") or issue.get("value_rub") is None:
            rows.append({"figi": issue["figi"], "status": "нет данных", "delta_rub": None})
            continue
        if issue.get("floater"):
            # Rate risk ≈ 0 to next reset; residual is credit spread, not the key-rate shift.
            delta = 0.0
            floater_total += float(issue["value_rub"])
        else:
            d_mod = float(issue["modified"])
            conv = float(issue["convexity"] or 0)
            delta = rate_stress(dirty_value=float(issue["value_rub"]), d_mod=d_mod, conv=conv, shift_yield=dy)
        total += delta
        rows.append(
            {
                "figi": issue["figi"],
                "delta_rub": delta,
                "delta_pct_issue": delta / float(issue["value_rub"]),
                "floater": bool(issue.get("floater")),
                "status": "ok",
            }
        )
    elapsed_ms = round((perf_counter() - started) * 1000.0, 3)
    return {
        "portfolio_id": portfolio_id,
        "shift_bp": shift_bp,
        "delta_rub": total if rows else None,
        "delta_pct_portfolio": (total / nav) if nav else None,
        "floater_nav_rub": floater_total if floater_total else None,
        "floater_note": "у флоатеров ставочный риск почти нулевой, остаётся кредитный спред",
        "issues": rows,
        "elapsed_ms": elapsed_ms,
        "methodology": METHOD_PATH,
        "as_of": book.get("as_of"),
        "source": book.get("source"),
    }


def attach_to_stress_library(payload: dict[str, Any], user_id: str) -> dict[str, Any]:
    if not is_enabled("qa_bonds") or not is_enabled("qa_stress_library"):
        return payload
    extra = []
    for bp in (100, -100, 200, -200):
        extra.append(portfolio_bond_stress(user_id, "paper", shift_bp=bp))
    out = dict(payload)
    out["bond_rate_stress"] = extra
    return out
