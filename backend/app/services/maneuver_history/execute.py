"""Next-session fills. Costs and the tax base come from prompt 36.

Cash tax is not computed: OQ-36-1. The broker table has no tariff, so a
missing rate stays «нет данных» and is not replaced with a made-up number.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Decimal

from app.services.target_portfolio.costs import (
    commission_rate,
    load_cost_table,
    trade_costs,
)
from app.services.target_portfolio.tax import fifo_realize, tax_base_for_year
from app.services.target_portfolio.types import TaxLot

MONEY = Decimal("0.01")
_EIGHT = Decimal("0.00000001")


@dataclass
class Ledger:
    cash: Decimal
    qty: dict[str, Decimal]
    lots: list[TaxLot]
    costs_complete: bool = True
    cost_drag: Decimal = Decimal("0")
    realized: list[dict[str, str]] = field(default_factory=list)
    seq: int = 0

    def wealth(self, prices: dict[str, Decimal]) -> Decimal | None:
        total = self.cash
        for ticker, qty in self.qty.items():
            if qty == 0:
                continue
            px = prices.get(ticker)
            if px is None:
                return None
            total += qty * px
        return total

    def wealth_after_costs(self, prices: dict[str, Decimal]) -> Decimal | None:
        if not self.costs_complete:
            return None
        base = self.wealth(prices)
        if base is None:
            return None
        return base - self.cost_drag


def open_ledger(
    qty: dict[str, Decimal],
    prices: dict[str, Decimal],
    acquired: date,
) -> Ledger:
    lots: list[TaxLot] = []
    held: dict[str, Decimal] = {}
    seq = 0
    for ticker in sorted(qty):
        amount = qty[ticker]
        if amount == 0:
            continue
        px = prices[ticker]
        lots.append(TaxLot(str(seq), ticker, amount, amount * px, acquired))
        held[ticker] = amount
        seq += 1
    return Ledger(cash=Decimal("0"), qty=held, lots=lots, seq=seq)


def orders_toward_weights(
    *,
    qty: dict[str, Decimal],
    prices: dict[str, Decimal],
    weights: dict[str, Decimal],
    nav: Decimal,
    lot: Decimal,
) -> list[dict[str, str]]:
    """Integer lots toward target weights, sized at the decision prices."""
    step = lot if lot > 0 else Decimal("1")
    names = set(qty) | set(weights)
    orders: list[dict[str, str]] = []
    for ticker in sorted(names):
        px = prices.get(ticker)
        if px is None or px <= 0 or nav <= 0:
            continue
        target_qty = nav * weights.get(ticker, Decimal("0")) / px
        delta = target_qty - qty.get(ticker, Decimal("0"))
        steps = (abs(delta) / step).to_integral_value(rounding=ROUND_DOWN)
        if steps == 0:
            continue
        signed = steps * step if delta > 0 else -(steps * step)
        held = qty.get(ticker, Decimal("0"))
        if signed < 0 and abs(signed) > held:
            signed = -held
        if signed == 0:
            continue
        side = "buy" if signed > 0 else "sell"
        orders.append({"ticker": ticker, "side": side, "qty": format(abs(signed), "f")})
    return orders


def net_orders(orders: list[dict[str, str]]) -> dict[str, Decimal]:
    net: dict[str, Decimal] = {}
    for order in orders:
        qty = Decimal(str(order["qty"]))
        signed = qty if order["side"] == "buy" else -qty
        ticker = str(order["ticker"]).upper()
        net[ticker] = net.get(ticker, Decimal("0")) + signed
    return {ticker: qty for ticker, qty in net.items() if qty != 0}


def _weights(qty: dict[str, Decimal], prices: dict[str, Decimal], cash: Decimal) -> dict[str, Decimal]:
    nav = cash
    for ticker, amount in qty.items():
        px = prices.get(ticker)
        if px is None:
            continue
        nav += amount * px
    if nav == 0:
        return {}
    out: dict[str, Decimal] = {}
    for ticker, amount in qty.items():
        px = prices.get(ticker)
        if px is None:
            continue
        out[ticker] = amount * px / nav
    return out


def _consume(lots: list[TaxLot], ticker: str, sell_qty: Decimal) -> list[TaxLot]:
    ordered = sorted(lots, key=lambda lot: (lot.acquired, lot.lot_id))
    left = sell_qty
    kept: list[TaxLot] = []
    for lot in ordered:
        if left <= 0 or lot.ticker != ticker:
            kept.append(lot)
            continue
        if lot.qty <= left:
            left -= lot.qty
            continue
        remain = lot.qty - left
        cost = (lot.cost * remain / lot.qty).quantize(MONEY, rounding=ROUND_HALF_EVEN)
        kept.append(TaxLot(lot.lot_id, lot.ticker, remain, cost, lot.acquired))
        left = Decimal("0")
    return kept


def fill_at_next_session(
    *,
    fill_on: date,
    prices: dict[str, Decimal],
    orders: list[dict[str, str]],
    ledger: Ledger,
) -> dict[str, str | int | list | dict]:
    """Fill at this session's prices. The caller passes only the next session.

    `fill_on` is the execution date. Sizing happened on the previous session.
    """
    if not orders:
        return {
            "status": "ok",
            "reason": "сделок не было",
            "filled": 0,
            "turnover": format(Decimal("0"), "f"),
            "costs_status": "сделок не было",
            "applied": {},
            "tax_rows": [],
        }
    before_qty = dict(ledger.qty)
    before_cash = ledger.cash
    table = load_cost_table()
    rate = commission_rate(table, "", "")
    applied: dict[str, str] = {}
    filled = 0
    costs_status = "ok"
    new_rows: list[dict[str, str]] = []
    for ticker, signed in sorted(net_orders(orders).items()):
        px = prices.get(ticker)
        if px is None or px <= 0:
            costs_status = "нет данных"
            ledger.costs_complete = False
            continue
        held = ledger.qty.get(ticker, Decimal("0"))
        if signed < 0 and abs(signed) > held:
            signed = -held
        if signed == 0:
            continue
        notional = abs(signed) * px
        costs = trade_costs(
            traded_notional=notional,
            rate=rate,
            spread_bps=None,
            slippage_bps=None,
        )
        if costs["status"] != "ok":
            costs_status = "нет данных"
            ledger.costs_complete = False
        else:
            total = costs.get("total")
            if total not in (None, ""):
                ledger.cost_drag += Decimal(str(total))
        if signed > 0:
            ledger.cash -= notional
            ledger.qty[ticker] = held + signed
            ledger.lots.append(TaxLot(str(ledger.seq), ticker, signed, notional, fill_on))
            ledger.seq += 1
        else:
            sell = abs(signed)
            rows = fifo_realize(
                ledger.lots,
                ticker=ticker,
                sell_qty=sell,
                sale_price=px,
                sold_on=fill_on,
            )
            new_rows.extend(rows)
            ledger.realized.extend(rows)
            ledger.lots = _consume(ledger.lots, ticker, sell)
            ledger.cash += notional
            ledger.qty[ticker] = held + signed
        applied[ticker] = format(signed, "f")
        filled += 1
    after = _weights(ledger.qty, prices, ledger.cash)
    before = _weights(before_qty, prices, before_cash)
    names = set(before) | set(after)
    moved = sum((abs(after.get(name, Decimal("0")) - before.get(name, Decimal("0"))) for name in names), Decimal("0"))
    turnover = (moved / Decimal("2")).quantize(_EIGHT, rounding=ROUND_HALF_EVEN)
    return {
        "status": "ok" if filled else "нет данных",
        "reason": "" if filled else "нет цены следующей сессии",
        "filled": filled,
        "turnover": format(turnover, "f"),
        "costs_status": costs_status,
        "applied": applied,
        "tax_rows": new_rows,
    }


def tax_summary(rows: list[dict[str, str]], *, year: int) -> dict[str, str | bool | None]:
    """Annual bases and cash from prompt 36. Cash waits for residency."""
    if not rows:
        block = tax_base_for_year([], year)
        return {
            "tax_base": str(block["tax_base"]),
            "tax_cash": block["tax_cash"],
            "tax_cash_computed": block["tax_cash"] is not None,
            "tax_cash_reason": str(block["tax_cash_reason"]),
        }
    years = sorted({int(row["year"]) for row in rows})
    total = Decimal("0")
    cash_total = Decimal("0")
    cash_known = True
    reason = ""
    for item in years:
        block = tax_base_for_year(rows, item)
        total += Decimal(str(block["tax_base"]))
        if block["tax_cash"] is None:
            cash_known = False
        else:
            cash_total += Decimal(str(block["tax_cash"]))
        reason = str(block["tax_cash_reason"])
    return {
        "tax_base": format(total.quantize(MONEY, rounding=ROUND_HALF_EVEN), "f"),
        "tax_cash": None
        if not cash_known
        else format(cash_total.quantize(MONEY, rounding=ROUND_HALF_EVEN), "f"),
        "tax_cash_computed": cash_known,
        "tax_cash_reason": reason,
    }
