"""Futures desk: live FORTS contracts, the user's futures, margin cushion, hedge inputs.

All contract figures come from the MOEX ISS FORTS board (initial margin, tick,
tick value, expiry, open interest). The hedge maths is done on the client from
the inputs returned here, so the slider answers instantly; the formulas are the
same as ``futures_risk.math`` and are covered by tests.
"""
from __future__ import annotations

import math
import statistics
import time
from datetime import date, datetime
from typing import Any

from app.core.logging import get_logger
from app.services.market_data.moex_iss_client import fetch_moex_iss_json
from app.services.price_history import moex as iss

logger = get_logger(__name__)

BOARD_URL = f"{iss.ISS}/engines/futures/markets/forts/securities.json"
_TTL = 60.0
_cache: dict[str, Any] = {"at": 0.0, "rows": []}

# Underlyings a Russian private investor actually uses, in display order.
# key: ISS ASSETCODE (upper). group drives the UI sections.
UNDERLYINGS: list[dict[str, str]] = [
    {"asset": "MIX", "title": "Индекс Мосбиржи", "group": "index", "hedge": "equity"},
    {"asset": "MXI", "title": "Индекс Мосбиржи (мини)", "group": "index", "hedge": "equity"},
    {"asset": "IMOEXF", "title": "Индекс Мосбиржи, вечный", "group": "index", "hedge": "equity"},
    {"asset": "RTS", "title": "Индекс РТС", "group": "index"},
    {"asset": "SI", "title": "Доллар / рубль", "group": "fx", "hedge": "USD"},
    {"asset": "USDRUBF", "title": "Доллар / рубль, вечный", "group": "fx", "hedge": "USD"},
    {"asset": "CNY", "title": "Юань / рубль", "group": "fx", "hedge": "CNY"},
    {"asset": "CNYRUBF", "title": "Юань / рубль, вечный", "group": "fx", "hedge": "CNY"},
    {"asset": "EU", "title": "Евро / рубль", "group": "fx", "hedge": "EUR"},
    {"asset": "BR", "title": "Нефть Brent", "group": "commodity"},
    {"asset": "NG", "title": "Природный газ", "group": "commodity"},
    {"asset": "GOLD", "title": "Золото", "group": "commodity"},
    {"asset": "GLDRUBF", "title": "Золото в рублях, вечный", "group": "commodity"},
    {"asset": "SILV", "title": "Серебро", "group": "commodity"},
    {"asset": "SBRF", "title": "Сбербанк", "group": "stock"},
    {"asset": "GAZR", "title": "Газпром", "group": "stock"},
    {"asset": "LKOH", "title": "Лукойл", "group": "stock"},
]
_BY_ASSET = {u["asset"]: u for u in UNDERLYINGS}
_FAR_FUTURE = "2090-01-01"


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _day(v: Any) -> date | None:
    try:
        return date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def contract_row(sec: dict[str, Any], md: dict[str, Any], *, today: date | None = None) -> dict[str, Any]:
    """One FORTS contract in plain terms (roubles, days, multiples)."""
    today = today or date.today()
    step = _num(sec.get("MINSTEP"))
    step_price = _num(sec.get("STEPPRICE"))
    point_value = (step_price / step) if step and step_price else None  # ₽ per 1.0 of price
    settle = _num(md.get("SETTLEPRICE")) or _num(sec.get("LASTSETTLEPRICE"))
    prev_settle = _num(sec.get("PREVSETTLEPRICE"))
    price = _num(md.get("LAST")) or settle or prev_settle
    margin = _num(sec.get("INITIALMARGIN"))
    expiry = _day(sec.get("LASTTRADEDATE"))
    perpetual = bool(expiry and expiry.isoformat() >= _FAR_FUTURE) or str(sec.get("SECID", "")).upper().endswith("RUBF") or str(sec.get("SECID", "")).upper() in {"IMOEXF", "SBERF", "GAZPF"}
    value = price * point_value if price is not None and point_value else None
    change = None
    if price is not None and prev_settle:
        change = price / prev_settle - 1.0
    asset = str(sec.get("ASSETCODE") or "").upper()
    meta = _BY_ASSET.get(asset, {})
    fee = _num(sec.get("BUYSELLFEE"))
    return {
        "secid": sec.get("SECID"),
        "shortname": sec.get("SHORTNAME"),
        "name": sec.get("SECNAME"),
        "asset": asset,
        "title": meta.get("title") or sec.get("SECNAME") or sec.get("SHORTNAME"),
        "group": meta.get("group") or "other",
        "hedge": meta.get("hedge"),
        "price": price,
        "prev_settle": prev_settle,
        "change": change,
        "tick": step,
        "tick_value": step_price,
        "point_value": point_value,
        "contract_value": value,
        "initial_margin": margin,
        "leverage": (value / margin) if value and margin else None,
        "expiry": None if perpetual or expiry is None else expiry.isoformat(),
        "days_to_expiry": None if perpetual or expiry is None else (expiry - today).days,
        "perpetual": perpetual,
        "lot": _num(sec.get("LOTVOLUME")),
        "open_interest": _num(md.get("OPENPOSITION")) or _num(sec.get("PREVOPENPOSITION")),
        "volume": _num(md.get("VOLTODAY")),
        "value_today": _num(md.get("VALTODAY")),
        "bid": _num(md.get("BID")),
        "ask": _num(md.get("OFFER")),
        "fee": fee,
        "swap_rate": _num(md.get("SWAPRATE")) if md.get("SWAPRATE") is not None else _num(sec.get("SWAPRATE")),
        "updated": md.get("UPDATETIME"),
    }


async def board(*, today: date | None = None) -> list[dict[str, Any]]:
    """Every FORTS futures contract (cached for a minute)."""
    if _cache["rows"] and time.monotonic() - _cache["at"] < _TTL:
        return _cache["rows"]
    import json
    import os
    from pathlib import Path

    fixture = os.environ.get("FUTURES_BOARD_FIXTURE", "").strip()  # offline dev / e2e only
    if fixture and Path(fixture).is_file():
        payload = json.loads(Path(fixture).read_text(encoding="utf-8"))
    else:
        payload = await fetch_moex_iss_json(BOARD_URL, {"iss.meta": "off", "iss.only": "securities,marketdata"})
    sec = {r.get("SECID"): r for r in iss.rows(payload, "securities") if r.get("SECID")}
    md = {r.get("SECID"): r for r in iss.rows(payload, "marketdata") if r.get("SECID")}
    out = [contract_row(s, md.get(k, {}), today=today) for k, s in sec.items()]
    out = [r for r in out if r["days_to_expiry"] is None or r["days_to_expiry"] >= 0]
    if out:
        _cache.update(at=time.monotonic(), rows=out)
    return out or _cache["rows"]


def key_contracts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Front contract per underlying (nearest expiry with open interest), plus the next one for roll."""
    out: list[dict[str, Any]] = []
    for u in UNDERLYINGS:
        chain = [r for r in rows if r["asset"] == u["asset"]]
        if not chain:
            continue
        live = [r for r in chain if (r.get("open_interest") or 0) > 0] or chain
        live.sort(key=lambda r: (r["days_to_expiry"] is None, r["days_to_expiry"] or 0))
        front = dict(live[0])
        nxt = live[1] if len(live) > 1 else None
        front["next_secid"] = nxt["secid"] if nxt else None
        front["next_price"] = nxt["price"] if nxt else None
        front["chain"] = [{"secid": r["secid"], "expiry": r["expiry"], "price": r["price"], "open_interest": r["open_interest"]} for r in live[:4]]
        out.append(front)
    return out


def _book(user_id: str, mode: str) -> tuple[list[Any], list[Any]]:
    from app.services.portfolio_book.store import get_book

    return get_book().positions(user_id=user_id, mode=mode), get_book().transactions(user_id=user_id, mode=mode)  # type: ignore[arg-type]


def my_futures(user_id: str, mode: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_secid = {str(r["secid"]).upper(): r for r in rows}
    positions, txns = _book(user_id, mode)
    entry: dict[str, float] = {}
    for t in txns:
        if t.kind == "trade" and t.qty and t.ticker:
            entry[t.ticker.upper()] = abs(float(t.amount) / float(t.qty))
    out = []
    for p in positions:
        c = by_secid.get((p.ticker or "").upper())
        if not c or not p.qty:
            continue
        qty = float(p.qty)
        pv = c.get("point_value") or 0.0
        price = c.get("price")
        day_var = (price - c["prev_settle"]) * pv * qty if price is not None and c.get("prev_settle") else None
        since = (price - entry[c["secid"].upper()]) * pv * qty if price is not None and c["secid"].upper() in entry else None
        dte = c.get("days_to_expiry")
        out.append(
            {
                **{k: c.get(k) for k in ("secid", "title", "price", "point_value", "initial_margin", "expiry", "days_to_expiry", "perpetual", "next_secid")},
                "qty": qty,
                "side": "long" if qty > 0 else "short",
                "notional": (price or 0) * pv * qty,
                "margin": (c.get("initial_margin") or 0) * abs(qty),
                "variation_today": day_var,
                "pnl_since_entry": since,
                "entry_price": entry.get(c["secid"].upper()),
                "roll_soon": dte is not None and dte <= 7,
            }
        )
    return out


def cash_rub(user_id: str, mode: str) -> float | None:
    from app.services.price_history import service as history

    positions, _ = _book(user_id, mode)
    total = 0.0
    seen = False
    for p in positions:
        if (p.ticker or "").upper() == "CASH":
            rate = history.fx_rate(p.ccy)
            if rate is not None:
                total += float(p.qty) * rate
                seen = True
    return total if seen else None


def hedge_inputs(user_id: str, mode: str) -> dict[str, Any]:
    """What a hedge needs: equity value and its beta to IMOEX, currency exposure, vols."""
    from app.services.price_history import service as history
    from app.services.risk_engine.service import _holdings_from_book, _value_rub

    holdings = _holdings_from_book(user_id, mode)
    idx = history.dated_returns("IMOEX")
    equity_value = 0.0
    beta_num = 0.0
    beta_den = 0.0
    fx: dict[str, float] = {}
    missing: list[str] = []
    port_days: dict[date, float] = {}
    for h in holdings:
        value = _value_rub(h)
        if value is None:
            missing.append(str(h["ticker"]))
            continue
        ccy = str(h.get("ccy") or "RUB").upper()
        if ccy != "RUB":
            fx[ccy] = fx.get(ccy, 0.0) + value
        meta = history.info(str(h["ticker"]))
        if meta.get("market") in {"bonds", "index", "fx"} or str(h["ticker"]) in {"LQDT", "TMON", "SBMM", "AKMM"}:
            continue
        mine = history.dated_returns(str(h["ticker"]))
        common = sorted(set(mine) & set(idx))[-252:]
        if len(common) < 60:
            missing.append(str(h["ticker"]))
            continue
        x = [idx[d] for d in common]
        y = [mine[d] for d in common]
        mx, my = statistics.fmean(x), statistics.fmean(y)
        var = sum((a - mx) ** 2 for a in x)
        if var <= 0:
            continue
        b = sum((a - mx) * (c - my) for a, c in zip(x, y)) / var
        equity_value += value
        beta_num += b * value
        beta_den += value
        for d in common:
            port_days[d] = port_days.get(d, 0.0) + value * mine[d]
    beta = beta_num / beta_den if beta_den else None
    idx_tail = [idx[d] for d in sorted(idx)[-252:]]
    index_vol = statistics.pstdev(idx_tail) * math.sqrt(252) if len(idx_tail) >= 60 else None
    port_vol = None
    if equity_value and len(port_days) >= 60:
        series = [port_days[d] / equity_value for d in sorted(port_days)[-252:]]
        port_vol = statistics.pstdev(series) * math.sqrt(252)
    return {
        "equity_value_rub": equity_value or None,
        "beta": beta,
        "index_vol": index_vol,
        "portfolio_vol": port_vol,
        "fx_exposure_rub": fx,
        "skipped": missing,
    }


def freshness(rows: list[dict[str, Any]], now: datetime | None = None) -> str:
    """How fresh the board is, judged from the data itself, not from credentials.

    A MOEX passport alone still gets the 15-minute delayed feed; only a paid
    real-time subscription removes the delay. So: compare the latest UPDATETIME
    with Moscow time during the session.
    Returns "realtime", "delayed" or "closed" (outside the trading session).
    """
    from zoneinfo import ZoneInfo

    msk = (now or datetime.now(ZoneInfo("Europe/Moscow"))).astimezone(ZoneInfo("Europe/Moscow"))
    in_session = msk.weekday() < 5 and ((9, 0) <= (msk.hour, msk.minute) <= (23, 50))
    if not in_session:
        return "closed"
    stamps: list[int] = []
    for r in rows:
        raw = str(r.get("updated") or "")
        try:
            h, m, *_ = (int(x) for x in raw.split(":"))
        except ValueError:
            continue
        stamps.append(h * 60 + m)
    if not stamps:
        return "delayed"
    lag = msk.hour * 60 + msk.minute - max(stamps)
    return "realtime" if 0 <= lag <= 5 else "delayed"


async def desk(user_id: str, mode: str = "paper") -> dict[str, Any]:
    try:
        rows = await board()
    except Exception as exc:  # noqa: BLE001
        logger.warning("futures_board_failed", error=str(exc)[:200])
        rows = []
    contracts = key_contracts(rows)
    return {
        "contracts": contracts,
        "positions": my_futures(user_id, mode, rows),
        "cash_rub": cash_rub(user_id, mode),
        "hedge": hedge_inputs(user_id, mode),
        "freshness": freshness(rows),
        "delayed": freshness(rows) != "realtime",
        "as_of": datetime.now().isoformat(timespec="minutes"),
        "source": "Московская биржа, срочный рынок FORTS",
        "data_status": "ok" if contracts else "нет данных",
        "reason": None if contracts else "биржа не ответила",
        "methodology": "/methodology/futures",
    }


def search(rows: list[dict[str, Any]], q: str, limit: int = 20) -> list[dict[str, Any]]:
    qq = q.strip().upper()
    if not qq:
        return []
    hits = [r for r in rows if qq in str(r["secid"]).upper() or qq in str(r.get("shortname") or "").upper() or qq in str(r.get("name") or "").upper() or qq in str(r.get("title") or "").upper()]
    hits.sort(key=lambda r: -(r.get("open_interest") or 0))
    return hits[:limit]
