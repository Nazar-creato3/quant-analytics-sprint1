"""59: price of investor timing and extra trades. Numbers from returns + book + K1."""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Any

from app.services.legal.catalog import load_ui_texts
from app.services.portfolio_book.store import get_book
from app.services.qa.feature_flags import is_enabled
from app.services.returns.service import as_dict as returns_as_dict
from app.services.returns.service import compute_returns
from app.services.risk_engine.series import get_dated_prices, get_series

KOPECK = Decimal("0.01")
PP = Decimal("0.0001")
DRAWDOWN_WINDOW = 60
DRAWDOWN_THRESHOLD = Decimal("0.10")
CHASE_WINDOW = 20
CHASE_THRESHOLD = Decimal("0.20")
HOLD_HORIZONS_DAYS = (63, 126, 252)  # ~3m / 6m / 12m trading days ≈ calendar span via price index


def analyze_decisions(
    *,
    user_id: str,
    mode: str,
    date_from: date | None = None,
    date_to: date | None = None,
    metric: str | None = None,
) -> dict[str, Any]:
    if not is_enabled("qa_59_decisions"):
        raise RuntimeError("qa_59_decisions off")
    texts = load_ui_texts().get("d59") or {}
    day = date_to or date.today()
    ret = compute_returns(user_id=user_id, mode=mode, period="inception", today=day)
    txns = [t for t in get_book().transactions(user_id=user_id, mode=mode) if t.event_time.date() <= day]
    if date_from:
        txns = [t for t in txns if t.event_time.date() >= date_from]
    closed, open_lots = _fifo_closed(txns)
    time_block = _time_cost(ret, txns)
    trade_block = _lazy_twin(txns, ret.end_value)
    disp = _disposition(closed, open_lots, _marks_from_book(user_id, mode))
    turnover = _turnover(txns, ret.end_value)
    holds = _holds(closed)
    thin = _thin_sample(txns, closed)
    k1 = _k1(user_id=user_id, mode=mode)
    time_rub = time_block.get("rubles")
    trade_rub = trade_block.get("rubles")
    total = None
    if isinstance(time_rub, Decimal) and isinstance(trade_rub, Decimal):
        total = (time_rub + trade_rub).quantize(KOPECK, rounding=ROUND_HALF_EVEN)
    trades = _metric_trades(metric, closed, txns)
    status = "ok"
    missing: list[str] = []
    if ret.data_status != "ok":
        status = "частично"
        missing.append("returns")
    if disp.get("data_status") != "ok":
        status = "частично"
        missing.append("disposition")
    if not txns:
        status = "нет данных"
    return {
        "data_status": status if txns else "нет данных",
        "reason": None if status == "ok" else ("частично: " + ", ".join(missing) if missing else "нет операций"),
        "as_of": day.isoformat(),
        "methodology": "/methodology/decisions",
        "texts": texts,
        "returns": returns_as_dict(ret),
        "time_cost": _dec_block(time_block),
        "trade_cost": _dec_block(trade_block),
        "disposition": disp,
        "drawdown_sales": _drawdown_sales(txns, thin=thin),
        "chase_buys": _chase_buys(txns, thin=thin),
        "turnover": _dec_block(turnover),
        "holding": holds,
        "total_rubles": str(total) if total is not None else None,
        "k1": k1,
        "thin": thin,
        "trades": trades,
    }


def _time_cost(ret: Any, txns: list[Any]) -> dict[str, Any]:
    twr = ret.twr
    mwr = ret.mwr
    end = ret.end_value
    deposits = [t for t in txns if t.kind == "deposit"]
    withdrawals = [t for t in txns if t.kind == "withdrawal"]
    if twr is None or mwr is None or end is None:
        return {"pp": None, "rubles": None, "data_status": "нет данных", "reason": ret.reason}
    coverage = getattr(ret, "coverage_from", None)
    if len(deposits) <= 1 and not withdrawals:
        return {
            "pp": Decimal("0.0000"),
            "rubles": Decimal("0.00"),
            "data_status": "ok",
            "reason": None,
            "coverage": str(coverage) if coverage else None,
        }
    pp = ((mwr - twr) * Decimal("100")).quantize(PP, rounding=ROUND_HALF_EVEN)
    denom = Decimal("1") + twr
    rubles = Decimal("0.00")
    if denom != 0:
        rubles = (end * (mwr - twr) / denom).quantize(KOPECK, rounding=ROUND_HALF_EVEN)
    return {"pp": pp, "rubles": rubles, "data_status": "ok", "reason": None, "coverage": str(coverage) if coverage else None}


def _lazy_twin(txns: list[Any], user_end: Decimal | None) -> dict[str, Any]:
    trades = [t for t in txns if t.kind == "trade"]
    extra = [t for t in trades[1:]] if trades else []
    if user_end is None:
        return {"rubles": None, "data_status": "нет данных", "reason": "нет конечной стоимости"}
    if not extra:
        return {"rubles": Decimal("0.00"), "data_status": "ok", "reason": None, "extra_trades": 0}
    return {
        "rubles": None,
        "data_status": "нет данных",
        "reason": "нет цен для ленивого двойника",
        "extra_trades": len(extra),
    }


def _fifo_closed(
    txns: list[Any],
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    lots: dict[str, list[dict[str, Any]]] = defaultdict(list)
    closed: list[dict[str, Any]] = []
    for t in sorted(txns, key=lambda x: x.event_time):
        if t.kind != "trade":
            continue
        qty = Decimal(t.qty)
        ticker = str(t.ticker or "").upper()
        if qty > 0:
            lots[ticker].append({"qty": qty, "amount": Decimal(t.amount), "when": t.event_time})
            continue
        need = abs(qty)
        while need > 0 and lots[ticker]:
            lot = lots[ticker][0]
            take = min(need, lot["qty"])
            cost = (lot["amount"] / lot["qty"] * take) if lot["qty"] else Decimal("0")
            proceeds = abs(Decimal(t.amount)) * (take / abs(qty)) if qty else Decimal("0")
            pnl = proceeds - cost
            closed.append(
                {
                    "ticker": ticker,
                    "qty": str(take),
                    "pnl": str(pnl.quantize(KOPECK, rounding=ROUND_HALF_EVEN)),
                    "opened": lot["when"].date().isoformat(),
                    "closed": t.event_time.date().isoformat(),
                    "hold_days": (t.event_time.date() - lot["when"].date()).days,
                    "gain": pnl > 0,
                    "loss": pnl < 0,
                    "external_id": t.external_id,
                }
            )
            lot["qty"] -= take
            lot["amount"] -= cost
            need -= take
            if lot["qty"] <= 0:
                lots[ticker].pop(0)
    open_lots = {k: [lot for lot in v if lot["qty"] > 0] for k, v in lots.items()}
    open_lots = {k: v for k, v in open_lots.items() if v}
    return closed, open_lots


def _marks_from_book(user_id: str, mode: str) -> dict[str, Decimal]:
    from app.services.risk_engine.service import _holdings_from_book

    marks: dict[str, Decimal] = {}
    for h in _holdings_from_book(user_id, mode):
        ticker = str(h.get("ticker") or "").upper()
        px = h.get("price")
        if not ticker or px in (None, ""):
            continue
        try:
            marks[ticker] = Decimal(str(px))
        except Exception:
            continue
    return marks


def _disposition(
    closed: list[dict[str, Any]],
    open_lots: dict[str, list[dict[str, Any]]],
    marks: dict[str, Decimal],
) -> dict[str, Any]:
    """Odean PGR/PLR: realized / (realized + paper), not share of sells."""
    rg = sum(1 for c in closed if c["gain"])
    rl = sum(1 for c in closed if c["loss"])
    pg = 0
    pl = 0
    unmarked = 0
    for ticker, lots in open_lots.items():
        mark = marks.get(ticker)
        for lot in lots:
            if mark is None:
                unmarked += 1
                continue
            cost = (lot["amount"] / lot["qty"]) if lot["qty"] else Decimal("0")
            if mark > cost:
                pg += 1
            elif mark < cost:
                pl += 1
    if rg + rl + pg + pl < 1:
        reason = "нет закрытых сделок" if not closed else "нет цен для открытых позиций"
        return {
            "data_status": "нет данных",
            "reason": reason,
            "pgr": None,
            "plr": None,
            "gap": None,
            "realized_gains": rg,
            "realized_losses": rl,
            "paper_gains": pg,
            "paper_losses": pl,
        }
    pgr = (Decimal(rg) / Decimal(rg + pg)) if (rg + pg) > 0 else None
    plr = (Decimal(rl) / Decimal(rl + pl)) if (rl + pl) > 0 else None
    n = rg + rl + pg + pl
    status = "ok" if n >= 20 and unmarked == 0 else "частично"
    reason = None
    if unmarked:
        reason = "нет цен для части открытых позиций"
    elif n < 20:
        reason = "мало данных для вывода"
    gap = None
    if pgr is not None and plr is not None:
        gap = str((pgr - plr).quantize(PP, rounding=ROUND_HALF_EVEN))
    return {
        "data_status": status,
        "reason": reason,
        "pgr": None if pgr is None else str(pgr.quantize(PP, rounding=ROUND_HALF_EVEN)),
        "plr": None if plr is None else str(plr.quantize(PP, rounding=ROUND_HALF_EVEN)),
        "gap": gap,
        "n": n,
        "realized_gains": rg,
        "realized_losses": rl,
        "paper_gains": pg,
        "paper_losses": pl,
        "note": "PGR и PLR по закрытым и открытым результатам (Odean).",
    }


def _average_portfolio_value(txns: list[Any], end: Decimal | None) -> Decimal | None:
    """(start capital + end value) / 2. Do not use end alone as the average."""
    if end is None:
        return None
    deposits = sum((abs(Decimal(t.amount)) for t in txns if t.kind == "deposit"), Decimal("0"))
    if deposits <= 0:
        return None
    return ((deposits + end) / Decimal("2")).quantize(KOPECK, rounding=ROUND_HALF_EVEN)


def _turnover(txns: list[Any], end: Decimal | None) -> dict[str, Any]:
    sells = sum((abs(t.amount) for t in txns if t.kind == "trade" and t.qty < 0), Decimal("0"))
    fees = sum((abs(t.amount) for t in txns if t.kind == "fee"), Decimal("0"))
    avg = _average_portfolio_value(txns, end)
    ratio = None
    if isinstance(avg, Decimal) and avg > 0:
        ratio = (sells / avg).quantize(PP, rounding=ROUND_HALF_EVEN)
    return {
        "sells": sells,
        "fees": fees,
        "avg_value": avg,
        "end_value": end,
        "turnover": ratio,
        "data_status": "ok" if avg is not None else "нет данных",
    }


def _holds(closed: list[dict[str, Any]]) -> dict[str, Any]:
    if not closed:
        return {"data_status": "нет данных", "days": [], "average_days": None}
    days = [int(c["hold_days"]) for c in closed]
    avg = Decimal(sum(days)) / Decimal(len(days))
    return {
        "data_status": "ok",
        "days": days,
        "average_days": str(avg.quantize(Decimal("0.1"), rounding=ROUND_HALF_EVEN)),
    }


def _thin_sample(txns: list[Any], closed: list[dict[str, Any]]) -> bool:
    if len(closed) < 20:
        return True
    if not txns:
        return True
    first = min(t.event_time.date() for t in txns)
    last = max(t.event_time.date() for t in txns)
    return (last - first).days < 365


def _k1(*, user_id: str, mode: str) -> dict[str, Any]:
    if not is_enabled("qa_k1_benchmark"):
        return {"status": "off", "alternatives": []}
    from app.services.benchmark_alt.service import as_dict, compare_simple_alternatives

    try:
        payload = as_dict(compare_simple_alternatives(user_id=user_id, mode=mode, period="inception"))
    except Exception as exc:
        return {"status": "нет данных", "alternatives": [], "reason": "ориентир недоступен", "error_class": type(exc).__name__}
    payload["status"] = payload.get("data_status")
    return payload


def _price_after_sessions(rows: list[tuple[date, float]], day: date, sessions: int) -> Decimal | None:
    ordered = sorted(rows, key=lambda x: x[0])
    dates = [d for d, _ in ordered]
    if day not in dates:
        earlier = [d for d in dates if d <= day]
        if not earlier:
            return None
        day = max(earlier)
    i = dates.index(day)
    j = i + sessions
    if j >= len(ordered):
        return None
    return Decimal(str(ordered[j][1]))


def _imoex_drawdown_by_date(rows: list[tuple[date, float]]) -> dict[date, Decimal]:
    """Drawdown vs max close over the prior DRAWDOWN_WINDOW sessions (inclusive)."""
    ordered = sorted(rows, key=lambda x: x[0])
    out: dict[date, Decimal] = {}
    closes: list[Decimal] = []
    for d, px in ordered:
        closes.append(Decimal(str(px)))
        window = closes[-DRAWDOWN_WINDOW:]
        peak = max(window)
        dd = Decimal("0") if peak <= 0 else (peak - closes[-1]) / peak
        out[d] = dd
    return out


def _drawdown_sales(txns: list[Any], *, thin: bool) -> dict[str, Any]:
    rows = get_dated_prices("IMOEX")
    if not rows:
        if get_series("IMOEX"):
            return {
                "data_status": "нет данных",
                "reason": "есть доходности IMOEX без дат сессий",
                "items": [],
                "thin": thin,
            }
        return {
            "data_status": "нет данных",
            "reason": "нет ряда IMOEX",
            "items": [],
            "thin": thin,
        }
    dd = _imoex_drawdown_by_date(rows)
    items: list[dict[str, Any]] = []
    for t in txns:
        if t.kind != "trade" or Decimal(t.qty) >= 0:
            continue
        day = t.event_time.date()
        depth = dd.get(day)
        if depth is None:
            earlier = [d for d in dd if d <= day]
            depth = dd[max(earlier)] if earlier else None
        if depth is None or depth < DRAWDOWN_THRESHOLD:
            continue
        ticker = str(t.ticker or "").upper()
        paper = get_dated_prices(ticker)
        sell_px = abs(Decimal(t.amount) / Decimal(t.qty)) if t.qty else None
        hold_deltas: dict[str, str | None] = {}
        for sessions, label in zip(HOLD_HORIZONS_DAYS, ("m3", "m6", "m12"), strict=True):
            future = _price_after_sessions(paper, day, sessions) if paper else None
            if sell_px is None or future is None:
                hold_deltas[label] = None
            else:
                hold_deltas[label] = str(
                    ((future - sell_px) * abs(Decimal(t.qty))).quantize(KOPECK, rounding=ROUND_HALF_EVEN)
                )
        items.append(
            {
                "ticker": ticker,
                "day": day.isoformat(),
                "imoex_drawdown": str(depth.quantize(PP, rounding=ROUND_HALF_EVEN)),
                "qty": str(abs(Decimal(t.qty))),
                "hold_delta_rub": hold_deltas,
            }
        )
    status = "ok" if items or rows else "нет данных"
    if thin:
        status = "частично"
    return {
        "data_status": status if rows else "нет данных",
        "reason": None if status == "ok" else ("мало данных для вывода" if thin else None),
        "items": items,
        "thin": thin,
    }


def _chase_buys(txns: list[Any], *, thin: bool) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    missing_tickers: list[str] = []
    any_series = False
    for t in txns:
        if t.kind != "trade" or Decimal(t.qty) <= 0:
            continue
        ticker = str(t.ticker or "").upper()
        paper = get_dated_prices(ticker)
        if not paper:
            if ticker and ticker not in missing_tickers:
                missing_tickers.append(ticker)
            continue
        any_series = True
        day = t.event_time.date()
        ordered = sorted(paper, key=lambda x: x[0])
        dates = [d for d, _ in ordered]
        earlier = [d for d in dates if d <= day]
        if len(earlier) < CHASE_WINDOW + 1:
            continue
        end_day = max(earlier)
        i = dates.index(end_day)
        j = i - CHASE_WINDOW
        if j < 0:
            continue
        px_now = Decimal(str(ordered[i][1]))
        px_then = Decimal(str(ordered[j][1]))
        if px_then <= 0:
            continue
        growth = (px_now - px_then) / px_then
        if growth < CHASE_THRESHOLD:
            continue
        hold_deltas: dict[str, str | None] = {}
        for sessions, label in zip(HOLD_HORIZONS_DAYS, ("m3", "m6", "m12"), strict=True):
            future = _price_after_sessions(paper, day, sessions)
            hold_deltas[label] = (
                None
                if future is None
                else str(
                    ((future - px_now) * Decimal(t.qty)).quantize(KOPECK, rounding=ROUND_HALF_EVEN)
                )
            )
        items.append(
            {
                "ticker": ticker,
                "day": day.isoformat(),
                "growth_20d": str(growth.quantize(PP, rounding=ROUND_HALF_EVEN)),
                "qty": str(Decimal(t.qty)),
                "hold_delta_rub": hold_deltas,
            }
        )
    if not any_series and missing_tickers:
        return {
            "data_status": "нет данных",
            "reason": "нет дневных цен бумаги",
            "items": [],
            "thin": thin,
        }
    status = "ok"
    reason = None
    if thin:
        status = "частично"
        reason = "мало данных для вывода"
    elif missing_tickers and items:
        status = "частично"
        reason = "нет цен для части бумаг"
    return {"data_status": status, "reason": reason, "items": items, "thin": thin}


def _metric_trades(metric: str | None, closed: list[dict[str, Any]], txns: list[Any]) -> list[dict[str, Any]]:
    if not metric:
        return closed
    if metric == "disposition":
        return closed
    if metric == "fees":
        return [
            {
                "ticker": t.ticker,
                "kind": t.kind,
                "amount": str(t.amount),
                "day": t.event_time.date().isoformat(),
            }
            for t in txns
            if t.kind == "fee"
        ]
    return closed


def _dec_block(block: dict[str, Any]) -> dict[str, Any]:
    out = dict(block)
    for key in ("pp", "rubles", "sells", "fees", "avg_value", "turnover"):
        val = out.get(key)
        if isinstance(val, Decimal):
            out[key] = str(val)
    return out
