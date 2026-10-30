"""Behavioral metrics from the user's own book (Prompt 15).

Disposition: Odean PGR/PLR from realized and paper outcomes. No advice.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from app.services.portfolio_book.store import Transaction, get_book
from app.services.qa.feature_flags import is_enabled

CONFIG_VERSION = "behavior.v1"
MIN_CLOSED = 8
FORBIDDEN = ("купите", "продайте", "должны", "лучше бы", "рекоменд")


def analyze_trades(trades: list[dict[str, Any]]) -> dict[str, Any]:
    if not is_enabled("qa_behavior"):
        raise RuntimeError("qa_behavior off")
    closed, open_lots, marks = _realize(trades)
    rg = sum(1 for c in closed if c["pnl"] > 0)
    rl = sum(1 for c in closed if c["pnl"] < 0)
    pg = 0
    pl = 0
    for ticker, lots in open_lots.items():
        mark = marks.get(ticker)
        if mark is None:
            continue
        for lot in lots:
            cost = Decimal(str(lot["price"]))
            if mark > cost:
                pg += 1
            elif mark < cost:
                pl += 1
    n_closed = len(closed)
    n = rg + rl + pg + pl
    if n_closed < MIN_CLOSED:
        text = _explain_text("insufficient", {"n": n_closed, "min_n": MIN_CLOSED})
        _assert_safe(text)
        return {
            "source": "behavior",
            "config_version": CONFIG_VERSION,
            "sample_size": n_closed,
            "insufficient": True,
            "signals": [],
            "text": text,
            "weekly": text,
        }
    pgr = (rg / (rg + pg)) if (rg + pg) > 0 else None
    plr = (rl / (rl + pl)) if (rl + pl) > 0 else None
    winners = [c for c in closed if c["pnl"] > 0]
    losers = [c for c in closed if c["pnl"] < 0]
    hold_w = _avg_days(winners)
    hold_l = _avg_days(losers)
    if pgr is not None and plr is not None:
        disp = pgr - plr
    elif pgr is not None and (rl + pl) == 0:
        disp = pgr
    elif plr is not None and (rg + pg) == 0:
        disp = -plr
    else:
        disp = 0.0
    after_up = sum(1 for c in closed if c.get("bought_after_up"))
    on_drop = sum(1 for c in closed if c.get("sold_on_drop"))
    text = _explain_text(
        "disposition",
        {
            "n": n,
            "pgr_pct": int(round((pgr or 0.0) * 100)),
            "plr_pct": int(round((plr or 0.0) * 100)),
            "hold_w": f"{hold_w:.1f}",
            "hold_l": f"{hold_l:.1f}",
        },
    )
    _assert_safe(text)
    return {
        "source": "behavior",
        "config_version": CONFIG_VERSION,
        "sample_size": n,
        "insufficient": False,
        "realized_gain_share": pgr,
        "realized_loss_share": plr,
        "realized_gains": rg,
        "realized_losses": rl,
        "paper_gains": pg,
        "paper_losses": pl,
        "disposition": disp,
        "hold_days_winners": hold_w,
        "hold_days_losers": hold_l,
        "sold_on_drop": on_drop,
        "bought_after_up": after_up,
        "signals": [
            {
                "id": "disposition",
                "present": disp > 0.15,
                "number": disp,
                "text": text,
            }
        ],
        "text": text,
        "weekly": text,
    }


def analyze_user(*, user_id: str, mode: str = "paper") -> dict[str, Any]:
    rows = get_book().transactions(user_id=user_id, mode=mode)  # type: ignore[arg-type]
    trades = [_txn_to_trade(t) for t in rows if t.kind == "trade"]
    return analyze_trades(trades)


def weekly_text(*, user_id: str, mode: str = "paper") -> str:
    return str(analyze_user(user_id=user_id, mode=mode).get("weekly") or "")


def _txn_to_trade(t: Transaction) -> dict[str, Any]:
    side = "buy" if t.qty > 0 else "sell"
    qty = abs(t.qty)
    price = (abs(t.amount) / qty) if qty else Decimal("0")
    return {
        "ticker": t.ticker,
        "side": side,
        "qty": qty,
        "price": price,
        "time": t.event_time,
    }


def _realize(
    trades: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]], dict[str, Decimal]]:
    lots: dict[str, list[dict[str, Any]]] = defaultdict(list)
    last_px: dict[str, Decimal] = {}
    closed: list[dict[str, Any]] = []
    ordered = sorted(trades, key=lambda x: x.get("time") or datetime.min.replace(tzinfo=timezone.utc))
    for tr in ordered:
        ticker = str(tr["ticker"]).upper()
        qty = Decimal(str(tr["qty"]))
        price = Decimal(str(tr["price"]))
        ts = tr.get("time") or datetime.now(timezone.utc)
        prev = last_px.get(ticker)
        bought_after_up = bool(prev is not None and price > prev and tr["side"] == "buy")
        sold_on_drop = bool(prev is not None and price < prev and tr["side"] == "sell")
        last_px[ticker] = price
        if tr["side"] == "buy":
            lots[ticker].append({"qty": qty, "price": price, "time": ts})
            continue
        remain = qty
        while remain > 0 and lots[ticker]:
            lot = lots[ticker][0]
            take = min(remain, lot["qty"])
            pnl = (price - lot["price"]) * take
            hold = (ts - lot["time"]).total_seconds() / 86400.0 if hasattr(ts - lot["time"], "total_seconds") else 0.0
            closed.append(
                {
                    "ticker": ticker,
                    "pnl": float(pnl),
                    "hold_days": hold,
                    "bought_after_up": bought_after_up,
                    "sold_on_drop": sold_on_drop,
                }
            )
            lot["qty"] -= take
            remain -= take
            if lot["qty"] == 0:
                lots[ticker].pop(0)
    open_lots = {k: [lot for lot in v if lot["qty"] > 0] for k, v in lots.items()}
    open_lots = {k: v for k, v in open_lots.items() if v}
    return closed, open_lots, last_px


def _avg_days(rows: list[dict[str, Any]]) -> float:
    if not rows:
        return 0.0
    return sum(float(r["hold_days"]) for r in rows) / len(rows)


def _explain_text(key: str, values: dict[str, Any]) -> str:
    try:
        from app.services.explanations.service import render
        from app.services.qa.feature_flags import is_enabled as flag

        if flag("qa_explanations"):
            block = render(key, values)
            return f"{block['phrase']} {block['detail']} {block['learn']}"
    except Exception:
        pass
    if key == "insufficient":
        return (
            f"Сигнал не показывается: закрытых сделок {values.get('n')}, минимум {values.get('min_n')}. "
            "Это ограничение выборки, не оценка качества решений."
        )
    return (
        f"По {values.get('n')} исходам (закрытые и открытые) доля фиксации прибыли "
        f"{values.get('pgr_pct')}%, доля фиксации убытка {values.get('plr_pct')}%."
    )


def _assert_safe(text: str) -> None:
    low = text.lower()
    for word in FORBIDDEN:
        if word in low:
            raise ValueError(f"forbidden wording: {word}")
