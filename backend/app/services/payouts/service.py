"""Portfolio payout calendar (prompt 57). Dividends first; bonds after 56 merge."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.services.payouts import store
from app.services.payouts.calendar_moex import last_buy_date
from app.services.qa.feature_flags import is_enabled

FIXTURE = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "payouts" / "universe.json"
NDFL = Decimal("0.13")
METHOD = "/methodology/payouts"
FOREIGN_NOTE = "налог может отличаться"


def _uni() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def ensure_fixtures() -> None:
    if store.dividends():
        return
    payload = _uni()
    store.put_dividends(list(payload["dividends"]))
    for ticker, gap in (payload.get("gaps") or {}).items():
        store.put_gap(ticker, gap)
    for pos in payload.get("positions") or []:
        if pos.get("price") is not None:
            store.put_price(str(pos["ticker"]), float(pos["price"]))


def _qty(ticker: str, user_id: str) -> Decimal:
    ensure_fixtures()
    try:
        from app.services.portfolio_book.service import positions_for

        for pos in positions_for(user_id=user_id, mode="paper"):
            if pos.ticker.upper() == ticker.upper() and pos.qty > 0:
                return pos.qty
    except Exception:
        pass
    for row in _uni().get("positions") or []:
        if str(row["ticker"]).upper() == ticker.upper():
            return Decimal(str(row["qty"]))
    return Decimal("0")


def _tax(amount: Decimal | None, *, foreign: bool) -> tuple[Decimal | None, str | None]:
    if foreign:
        return None, FOREIGN_NOTE
    if amount is None:
        return None, None
    return (amount * NDFL).quantize(Decimal("0.01")), str(NDFL)


def _to_event(row: dict[str, Any], qty: Decimal) -> dict[str, Any]:
    record = date.fromisoformat(str(row["record_date"])) if row.get("record_date") else None
    broker = date.fromisoformat(str(row["last_buy_date_broker"])) if row.get("last_buy_date_broker") else None
    last_buy, last_src = (None, None)
    if record is not None:
        last_buy, last_src = last_buy_date(record, from_broker=broker)
    foreign = bool(row.get("foreign"))
    unit = None if row.get("amount_gross") is None else Decimal(str(row["amount_gross"]))
    gross = None if unit is None else (unit * qty).quantize(Decimal("0.01"))
    tax, tax_note = _tax(gross, foreign=foreign)
    net = None if gross is None or tax is None else (gross - tax).quantize(Decimal("0.01"))
    pay = row.get("payment_date") or row.get("record_date")
    return {
        "date": pay,
        "type": row.get("type") or "dividend",
        "instrument": {
            "figi": row.get("figi"),
            "ticker": row.get("ticker"),
            "name": row.get("name"),
            "secid": row.get("secid"),
        },
        "quantity": str(qty),
        "amount_gross_rub": None if gross is None else float(gross),
        "tax_rub": None if tax is None else float(tax),
        "amount_net_rub": None if net is None else float(net),
        "status": row.get("status"),
        "status_label": (
            "ориентир по прошлым годам, не объявлен" if row.get("status") == "estimated" else row.get("status")
        ),
        "last_buy_date": None if last_buy is None else last_buy.isoformat(),
        "last_buy_source": last_src,
        "record_date": row.get("record_date"),
        "declared_date": row.get("declared_date"),
        "source": row.get("source"),
        "as_of": _uni().get("as_of"),
        "foreign": foreign,
        "tax_note": tax_note,
        "methodology": METHOD,
    }


def _bond_events(user_id: str) -> list[dict[str, Any]]:
    try:
        from app.services.bonds import store as bonds
        from app.services.bonds.service import ensure_fixtures as bond_fix

        bond_fix()
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for figi, ref in bonds.all_refs().items():
        qty = _qty(figi, user_id)
        if qty <= 0:
            continue
        for cf in ref.get("cashflows") or []:
            on = str(cf.get("on_date") or "")[:10]
            if not on:
                continue
            unit = cf.get("amount_per_bond")
            if unit is None:
                continue
            kind = str(cf.get("type") or "coupon")
            mapped = "coupon"
            if "amort" in kind:
                mapped = "amortization"
            elif "put" in kind or "offer" in kind:
                mapped = "offer"
            elif "redemption" in kind:
                mapped = "maturity"
            gross = (Decimal(str(unit)) * qty).quantize(Decimal("0.01"))
            tax = (gross * NDFL).quantize(Decimal("0.01")) if mapped == "coupon" else Decimal("0")
            out.append(
                {
                    "date": on,
                    "type": mapped,
                    "instrument": {"figi": figi, "ticker": figi, "name": ref.get("name")},
                    "quantity": str(qty),
                    "amount_gross_rub": float(gross),
                    "tax_rub": float(tax),
                    "amount_net_rub": float(gross - tax),
                    "status": "scheduled" if cf.get("status") == "known" else "estimated",
                    "last_buy_date": None,
                    "source": "календарь выплат",
                    "as_of": ref.get("as_of"),
                    "methodology": METHOD,
                }
            )
    return out


def _book_qty(user_id: str, mode: str = "paper") -> dict[str, Decimal]:
    from app.services.portfolio_book.service import positions_for

    out: dict[str, Decimal] = {}
    for pos in positions_for(user_id=user_id, mode=mode):  # type: ignore[arg-type]
        if pos.ticker and pos.ticker.upper() != "CASH" and pos.qty > 0:
            out[pos.ticker.upper()] = out.get(pos.ticker.upper(), Decimal("0")) + pos.qty
    return out


def _real_events(user_id: str, today: date | None = None) -> list[dict[str, Any]]:
    """Payouts of the user's own positions from MOEX ISS (dividends, coupons, amortisations).

    Declared and scheduled amounts as published. Where nothing is declared yet but the
    company paid in the same season last year, an «estimated» row repeats last year's
    amount — clearly marked, never mixed into the «declared» total.
    """
    from app.services.price_history import store as ph

    day0 = today or date.today()
    events: list[dict[str, Any]] = []
    for ticker, qty in _book_qty(user_id).items():
        pay = ph.read(f"PAY_{ticker}") or {}
        if pay.get("kind") == "dividend":
            rows = pay.get("dividends") or []
            future = [r for r in rows if str(r["record_date"]) >= day0.isoformat()]
            for r in future:
                rec = date.fromisoformat(r["record_date"])
                events.append(_to_event(_div_row(ticker, r["amount"], rec, "declared", r.get("ccy")), qty))
            for r in rows:
                rec = date.fromisoformat(r["record_date"])
                if not (day0 - timedelta(days=365) <= rec < day0):
                    continue
                guess = rec.replace(year=rec.year + 1) if not (rec.month == 2 and rec.day == 29) else rec + timedelta(days=365)
                if any(abs((date.fromisoformat(f["record_date"]) - guess).days) <= 75 for f in future):
                    continue
                events.append(_to_event(_div_row(ticker, r["amount"], guess, "estimated", r.get("ccy")), qty))
        elif pay.get("kind") == "bond":
            last_known = None
            for c in pay.get("coupons") or []:
                if c.get("amount") is not None and str(c["date"]) < day0.isoformat():
                    last_known = c["amount"]
            for c in pay.get("coupons") or []:
                if str(c["date"]) < day0.isoformat():
                    continue
                known = c.get("amount") is not None
                unit = c["amount"] if known else last_known
                events.append(_bond_row(ticker, "coupon", c["date"], unit, qty, "scheduled" if known else "estimated"))
                if known:
                    last_known = c["amount"]
            amort = [a for a in pay.get("amortizations") or [] if str(a["date"]) >= day0.isoformat()]
            for i, a in enumerate(amort):
                kind = "maturity" if i == len(amort) - 1 else "amortization"
                events.append(_bond_row(ticker, kind, a["date"], a["amount"], qty, "scheduled"))
    return events


def _div_row(ticker: str, amount: float | None, record: date, status: str, ccy: str | None) -> dict[str, Any]:
    # Russian issuers pay within 10 working days (nominee) — about two calendar weeks.
    return {
        "ticker": ticker,
        "secid": ticker,
        "name": ticker,
        "type": "dividend",
        "amount_gross": amount,
        "currency": ccy or "RUB",
        "declared_date": None,
        "record_date": record.isoformat(),
        "last_buy_date_broker": None,
        "payment_date": (record + timedelta(days=14)).isoformat(),
        "status": status,
        "source": "Московская биржа" if status == "declared" else "по выплате прошлого года",
        "foreign": bool(ccy and ccy not in {"RUB", "SUR"}),
    }


def _bond_row(ticker: str, kind: str, on: str, unit: float | None, qty: Decimal, status: str) -> dict[str, Any]:
    gross = None if unit is None else (Decimal(str(unit)) * qty).quantize(Decimal("0.01"))
    tax = None if gross is None else ((gross * NDFL).quantize(Decimal("0.01")) if kind == "coupon" else Decimal("0"))
    return {
        "date": on,
        "type": kind,
        "instrument": {"figi": None, "ticker": ticker, "name": ticker, "secid": ticker},
        "quantity": str(qty),
        "amount_gross_rub": None if gross is None else float(gross),
        "tax_rub": None if tax is None else float(tax),
        "amount_net_rub": None if gross is None or tax is None else float(gross - tax),
        "status": status,
        "status_label": "ориентир: размер купона ещё не объявлен, взят прошлый" if status == "estimated" else "по графику выпуска",
        "last_buy_date": None,
        "source": "Московская биржа",
        "methodology": METHOD,
    }


def portfolio_cashflows(
    user_id: str,
    portfolio_id: str,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    types: str | None = None,
) -> dict[str, Any]:
    if not is_enabled("qa_payouts"):
        return {"status": "flag_off"}
    from app.services.price_history import store as ph

    wanted = {p.strip() for p in (types or "").split(",") if p.strip()}
    start = date.fromisoformat(date_from) if date_from else date.today()
    end = date.fromisoformat(date_to) if date_to else date.today() + timedelta(days=400)
    if ph.enabled():
        events = []
        for ev in _real_events(user_id):
            day = date.fromisoformat(str(ev["date"])[:10]) if ev.get("date") else None
            if day is None or day < start or day > end or (wanted and ev["type"] not in wanted):
                continue
            events.append(ev)
        events.sort(key=lambda e: str(e.get("date") or ""))
        return {
            "portfolio_id": portfolio_id,
            "user_id": user_id,
            "events": events,
            "data_status": "ok" if events else "нет данных",
            "methodology": METHOD,
            "as_of": date.today().isoformat(),
            "source": "Московская биржа",
            "texts_key": "payouts",
        }
    ensure_fixtures()
    start = date.fromisoformat(date_from) if date_from else date(2026, 1, 1)
    end = date.fromisoformat(date_to) if date_to else date(2027, 12, 31)
    events = []
    for row in store.dividends():
        qty = _qty(str(row["ticker"]), user_id)
        if qty <= 0:
            continue
        ev = _to_event(row, qty)
        day = date.fromisoformat(str(ev["date"])[:10]) if ev.get("date") else None
        if day is None or day < start or day > end:
            continue
        if wanted and ev["type"] not in wanted:
            continue
        events.append(ev)
    for ev in _bond_events(user_id):
        day = date.fromisoformat(str(ev["date"])[:10])
        if day < start or day > end:
            continue
        if wanted and ev["type"] not in wanted:
            continue
        events.append(ev)
    events.sort(key=lambda e: str(e.get("date") or ""))
    return {
        "portfolio_id": portfolio_id,
        "user_id": user_id,
        "events": events,
        "data_status": "ok" if events else "нет данных",
        "methodology": METHOD,
        "as_of": _uni().get("as_of"),
        "source": "календарь выплат",
        "texts_key": "payouts",
    }


def cashflow_summary(user_id: str, portfolio_id: str, months: int = 12) -> dict[str, Any]:
    book = portfolio_cashflows(user_id, portfolio_id)
    if book.get("status") == "flag_off":
        return book
    from app.services.price_history import store as ph

    today = date.today() if ph.enabled() else date.fromisoformat(str(_uni()["as_of"]))
    horizon = today + timedelta(days=int(months) * 31)
    buckets: dict[str, dict[str, float]] = {}
    declared_net = 0.0
    estimated_note = 0
    by_type: dict[str, float] = {}
    for ev in book.get("events") or []:
        if not ev.get("date"):
            continue
        day = date.fromisoformat(str(ev["date"])[:10])
        if day < today or day > horizon:
            continue
        key = day.strftime("%Y-%m")
        bucket = buckets.setdefault(key, {"gross": 0.0, "tax": 0.0, "net": 0.0, "estimated_net": 0.0})
        if ev.get("amount_gross_rub") is not None:
            bucket["gross"] += float(ev["amount_gross_rub"])
        if ev.get("tax_rub") is not None:
            bucket["tax"] += float(ev["tax_rub"])
        if ev.get("amount_net_rub") is not None:
            bucket["net"] += float(ev["amount_net_rub"])
            if ev.get("status") == "estimated":
                estimated_note += 1
                bucket["estimated_net"] += float(ev["amount_net_rub"])
            else:
                declared_net += float(ev["amount_net_rub"])
                by_type[ev["type"]] = by_type.get(ev["type"], 0.0) + float(ev["amount_net_rub"])
    yields = dividend_yields(user_id) if ph.enabled() else dividend_yields()
    return {
        "portfolio_id": portfolio_id,
        "months": months,
        "by_month": buckets,
        "passive_declared_net_12m": declared_net if declared_net else None,
        "estimated_net_12m": sum(b["estimated_net"] for b in buckets.values()) or None,
        "estimated_events": estimated_note,
        "by_type": by_type,
        "yields": yields,
        "methodology": METHOD,
        "as_of": _uni().get("as_of"),
        "data_status": "ok" if buckets else "нет данных",
    }


def dividend_yields(user_id: str | None = None) -> dict[str, Any]:
    if user_id is not None:
        return _real_yields(user_id)
    trailing = _uni().get("trailing_12m_declared") or {}
    rows = []
    weighted = 0.0
    nav = 0.0
    for pos in _uni().get("positions") or []:
        ticker = str(pos["ticker"])
        px = store.price(ticker)
        trail = trailing.get(ticker)
        if px is None or px <= 0 or trail is None:
            rows.append({"ticker": ticker, "yield": None, "status": "нет данных"})
            continue
        yld = float(trail) / float(px)
        value = float(pos["qty"]) * float(px)
        weighted += yld * value
        nav += value
        rows.append({"ticker": ticker, "yield": yld, "status": "ok"})
    return {
        "issues": rows,
        "portfolio": (weighted / nav) if nav else None,
        "window": "12m declared",
    }


def _real_yields(user_id: str) -> dict[str, Any]:
    """Trailing 12-month dividends (by record date) over the latest close, per holding."""
    from app.services.price_history import service as history
    from app.services.price_history import store as ph

    cutoff = (date.today() - timedelta(days=365)).isoformat()
    rows, weighted, nav = [], 0.0, 0.0
    for ticker, qty in _book_qty(user_id).items():
        pay = ph.read(f"PAY_{ticker}") or {}
        mark = history.last(ticker)
        if pay.get("kind") != "dividend" or not mark:
            continue
        trail = sum(float(r["amount"]) for r in pay.get("dividends") or [] if cutoff <= str(r["record_date"]) <= date.today().isoformat())
        yld = trail / mark[1] if mark[1] > 0 else None
        rows.append({"ticker": ticker, "yield": yld, "status": "ok" if yld is not None else "нет данных"})
        if yld is not None:
            value = float(qty) * mark[1]
            weighted += yld * value
            nav += value
    return {"issues": rows, "portfolio": (weighted / nav) if nav else None, "window": "12m by record date"}


def dividend_gap(ticker: str) -> dict[str, Any]:
    ensure_fixtures()
    row = store.gap(ticker)
    if not row:
        return {"ticker": ticker, "status": "нет данных", "label": "по прошлым данным, не прогноз"}
    return {**row, "ticker": ticker, "status": "ok", "label": "по прошлым данным, не прогноз"}


def reinvest_scenario(user_id: str) -> dict[str, Any]:
    try:
        from app.services.benchmark_alt.service import compare_simple_alternatives

        payload = compare_simple_alternatives(user_id=user_id, mode="paper")
        return {
            "status": "ok",
            "k1": payload,
            "note": "сценарий реинвестирования берёт те же потоки, что простая альтернатива",
        }
    except Exception:
        return {"status": "нет данных", "reason": "нет данных"}


def to_ics(events: list[dict[str, Any]]) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Quant Analytics//Выплаты//RU",
        "CALSCALE:GREGORIAN",
    ]
    for ev in events:
        if not ev.get("date"):
            continue
        day = str(ev["date"])[:10].replace("-", "")
        ticker = ev.get("instrument", {}).get("ticker") or "выплата"
        kind = {
            "dividend": "дивиденд",
            "coupon": "купон",
            "fund_payout": "выплата фонда",
            "amortization": "амортизация",
            "offer": "оферта",
            "maturity": "погашение",
        }.get(str(ev.get("type") or ""), "выплата")
        uid = f"{ticker}-{day}-{ev.get('type')}@quant-analytics"
        summary = f"{kind} {ticker}"
        desc = f"нетто {ev.get('amount_net_rub') if ev.get('amount_net_rub') is not None else 'нет данных'}"
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTAMP:{day}T000000Z",
                f"DTSTART;VALUE=DATE:{day}",
                f"SUMMARY:{summary}",
                f"DESCRIPTION:{desc}",
                "END:VEVENT",
            ]
        )
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def notify_copy(*, kind: str, amount: float | None, days: int = 3) -> str:
    if kind == "last_buy":
        return f"Через {days} дн. последний день покупки по бумаге из портфеля. Расчёт по вашим данным."
    if amount is None:
        return "Сегодня дата выплаты. Сумма: нет данных."
    return f"Поступило ожидаемо {amount:.2f} ₽. Расчёт по объявленным событиям."
