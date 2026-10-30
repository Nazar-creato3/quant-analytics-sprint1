"""Portfolio book math for Prompt 01B goldens.

Money quantities are Decimal. Methodology:
- TWR: geometric link of sub-period returns split at cash-flow dates
  (GIPS-style; CF at period end does not enter that period's return).
- MWR: IRR of investor cash flows (XIRR, actual/365).
- Bond dirty price = clean + ACI (НКД).
- Future contribution to NAV is variation margin, not notional.
- Untraded valuation day uses last available price (explicit type).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Iterable, Literal, Sequence

Instrument = Literal["equity", "bond", "future", "crypto", "fx_cash"]
PriceType = Literal["official_close", "last_available"]

TWOPLACES = Decimal("0.00000001")
MONEY = Decimal("0.00000001")


def _d(value: Decimal | int | str | float) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    return Decimal(value)


@dataclass(frozen=True)
class Position:
    symbol: str
    qty: Decimal
    ccy: str
    instrument: Instrument
    aci: Decimal = Decimal("0")
    variation_margin: Decimal = Decimal("0")


@dataclass(frozen=True)
class PriceQuote:
    symbol: str
    as_of: date
    price: Decimal
    ccy: str
    source: str
    price_type: PriceType
    license_label: str = "synthetic_golden"


@dataclass(frozen=True)
class FxRate:
    pair: str
    as_of: date
    rate: Decimal
    source: str


@dataclass(frozen=True)
class CashFlow:
    as_of: date
    amount_base: Decimal
    kind: str


@dataclass
class BookState:
    as_of: date
    base_ccy: str
    cash_base: Decimal
    positions: list[Position] = field(default_factory=list)
    ops_hash: tuple[str, ...] = ()


def convert_ccy(amount: Decimal, rate: Decimal) -> Decimal:
    """Convert using a quoted rate (1 foreign = rate base)."""
    return (amount * rate).quantize(MONEY, rounding=ROUND_HALF_EVEN)


def convert_roundtrip(amount: Decimal, rate: Decimal) -> Decimal:
    """Foreign → base → foreign. Residual is rounding only."""
    if rate == 0:
        raise ValueError("FX rate must be non-zero.")
    base = convert_ccy(amount, rate)
    return (base / rate).quantize(MONEY, rounding=ROUND_HALF_EVEN)


def position_nav(position: Position, quote: PriceQuote, fx_to_base: Decimal) -> Decimal:
    if position.instrument == "future":
        return convert_ccy(position.variation_margin, fx_to_base)
    dirty = quote.price + position.aci
    return convert_ccy(position.qty * dirty, fx_to_base)


def portfolio_value(
    positions: Sequence[Position],
    quotes: dict[str, PriceQuote],
    fx: dict[str, Decimal],
    cash_base: Decimal,
) -> Decimal:
    total = _d(cash_base)
    for position in positions:
        quote = quotes.get(position.symbol)
        if quote is None:
            raise KeyError(f"missing price for {position.symbol}")
        rate = fx.get(position.ccy, Decimal("1"))
        total += position_nav(position, quote, rate)
    return total.quantize(MONEY, rounding=ROUND_HALF_EVEN)


def weights_and_hhi(
    positions: Sequence[Position],
    quotes: dict[str, PriceQuote],
    fx: dict[str, Decimal],
    cash_base: Decimal,
) -> tuple[dict[str, Decimal], Decimal]:
    navs: dict[str, Decimal] = {"CASH": _d(cash_base)}
    for position in positions:
        quote = quotes[position.symbol]
        rate = fx.get(position.ccy, Decimal("1"))
        navs[position.symbol] = navs.get(position.symbol, Decimal("0")) + position_nav(
            position, quote, rate
        )
    total = sum(navs.values(), Decimal("0"))
    if total == 0:
        raise ValueError("portfolio value is zero")
    weights = {key: (value / total) for key, value in navs.items() if value != 0}
    hhi = sum((weight * weight for weight in weights.values()), Decimal("0"))
    return weights, hhi


def time_weighted_return(period_start_end: Sequence[tuple[Decimal, Decimal]]) -> Decimal:
    """Link (end/start - 1). Cash flows must already be stripped from end."""
    growth = Decimal("1")
    for start, end in period_start_end:
        if start <= 0:
            raise ValueError("TWR start value must be positive.")
        growth *= end / start
    return (growth - Decimal("1")).quantize(TWOPLACES, rounding=ROUND_HALF_EVEN)


def money_weighted_return(
    flows: Sequence[tuple[date, Decimal]],
    *,
    guess: Decimal = Decimal("0.1"),
) -> Decimal:
    """Annualized IRR (actual/365) via Newton steps, then bisection fallback."""
    if len(flows) < 2:
        raise ValueError("MWR needs at least two cash flows.")
    t0 = flows[0][0]

    def npv(rate: Decimal) -> Decimal:
        total = Decimal("0")
        for as_of, amount in flows:
            years = Decimal((as_of - t0).days) / Decimal("365")
            total += amount / ((Decimal("1") + rate) ** years)
        return total

    rate = guess
    for _ in range(40):
        base = npv(rate)
        bumped = npv(rate + Decimal("0.000001"))
        deriv = (bumped - base) / Decimal("0.000001")
        if deriv == 0:
            break
        nxt = rate - base / deriv
        if abs(nxt - rate) < Decimal("0.0000001"):
            rate = nxt
            break
        rate = nxt
    if abs(npv(rate)) < Decimal("0.01"):
        return rate.quantize(TWOPLACES, rounding=ROUND_HALF_EVEN)

    lo, hi = Decimal("-0.9"), Decimal("5")
    for _ in range(80):
        mid = (lo + hi) / 2
        if npv(mid) > 0:
            lo = mid
        else:
            hi = mid
    return ((lo + hi) / 2).quantize(TWOPLACES, rounding=ROUND_HALF_EVEN)


def euler_component_var(
    weights: Sequence[float],
    covariance_matrix: Sequence[Sequence[float]],
    portfolio_var: float,
) -> list[float]:
    """Euler allocation of parametric VaR: w_i * (Σw)_i / (w'Σw) * VaR."""
    from app.services.quant_math.core import portfolio_variance

    variance = portfolio_variance(weights, covariance_matrix)
    if variance == 0.0:
        return [0.0 for _ in weights]
    allocated: list[float] = []
    for i, weight in enumerate(weights):
        sigma_w = sum(
            covariance_matrix[i][j] * weights[j] for j in range(len(weights))
        )
        allocated.append(weight * sigma_w / variance * portfolio_var)
    return allocated


def apply_operations(operations: Iterable[dict]) -> BookState:
    """Replay a dated operation list into cash + positions.

    Same-day ops are applied in the given order. Callers that need
    order-independence should sort by (as_of, op_id) first.
    """
    cash = Decimal("0")
    qty: dict[str, Decimal] = {}
    meta: dict[str, tuple[str, str]] = {}
    aci: dict[str, Decimal] = {}
    vm: dict[str, Decimal] = {}
    last = date(1970, 1, 1)
    fingerprints: list[str] = []
    for raw in operations:
        fingerprints.append(str(raw.get("op_id") or raw))
        as_of = date.fromisoformat(str(raw["as_of"]))
        last = max(last, as_of)
        kind = raw["kind"]
        if kind in {"deposit", "withdraw", "dividend", "coupon", "variation"}:
            cash += _d(raw["amount_base"])
        elif kind == "buy":
            symbol = raw["symbol"]
            cash -= _d(raw["amount_base"])
            qty[symbol] = qty.get(symbol, Decimal("0")) + _d(raw["qty"])
            meta[symbol] = (raw.get("ccy", "RUB"), raw.get("instrument", "equity"))
        elif kind == "sell":
            symbol = raw["symbol"]
            cash += _d(raw["amount_base"])
            qty[symbol] = qty.get(symbol, Decimal("0")) - _d(raw["qty"])
            meta[symbol] = (raw.get("ccy", "RUB"), raw.get("instrument", "equity"))
        elif kind == "split":
            symbol = raw["symbol"]
            qty[symbol] = qty.get(symbol, Decimal("0")) * _d(raw["factor"])
        elif kind == "set_aci":
            aci[raw["symbol"]] = _d(raw["aci"])
        elif kind == "set_vm":
            vm[raw["symbol"]] = _d(raw["variation_margin"])
            cash += _d(raw.get("amount_base", "0"))
        else:
            raise ValueError(f"unknown operation kind: {kind}")
    positions = [
        Position(
            symbol=symbol,
            qty=quantity,
            ccy=meta.get(symbol, ("RUB", "equity"))[0],
            instrument=meta.get(symbol, ("RUB", "equity"))[1],  # type: ignore[arg-type]
            aci=aci.get(symbol, Decimal("0")),
            variation_margin=vm.get(symbol, Decimal("0")),
        )
        for symbol, quantity in qty.items()
        if quantity != 0
    ]
    return BookState(as_of=last, base_ccy="RUB", cash_base=cash, positions=positions, ops_hash=tuple(fingerprints))


def same_day_canonical(operations: Sequence[dict]) -> list[dict]:
    def _key(item: dict) -> tuple[str, int, str]:
        raw = str(item.get("op_id", ""))
        numeric = int(raw) if raw.isdigit() else 10**9
        return (str(item["as_of"]), numeric, raw)

    return sorted(operations, key=_key)


def next_day(as_of: date) -> date:
    return as_of + timedelta(days=1)
