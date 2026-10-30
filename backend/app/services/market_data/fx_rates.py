"""Instrument currency and USD conversion for sizing.

Position sizes are kept in USD and quantities internally as USD-notional
over native price, which keeps P&L and risk correct as ratios. A real
broker order needs the true share count, so the USD notional is converted
into the instrument's currency here. No rate → no conversion (callers
refuse the order rather than guess).
"""
from __future__ import annotations

from app.core.logging import get_logger

logger = get_logger(__name__)

_PAIR_FOR = {"RUB": "USD000UTSTOM"}


def instrument_currency(ticker: str) -> str:
    from app.services.market_data.moex_currency import is_moex_currency_ticker
    from app.services.market_data.moex_spot import is_moex_ticker

    raw = (ticker or "").strip().upper()
    if is_moex_currency_ticker(raw) or is_moex_ticker(raw):
        return "RUB"
    return "USD"


async def usd_per_unit(currency: str) -> float | None:
    """How many USD one unit of ``currency`` is worth (USD → 1.0)."""
    ccy = (currency or "USD").upper()
    if ccy == "USD":
        return 1.0
    pair = _PAIR_FOR.get(ccy)
    if not pair:
        return None
    from app.services.market_data.moex_currency import get_moex_currency_quote

    try:
        quote = await get_moex_currency_quote(pair)
    except Exception as exc:  # noqa: BLE001
        logger.warning("fx_quote_failed", currency=ccy, error=str(exc)[:120])
        return None
    try:
        rate = float((quote or {}).get("price") or 0)
    except (TypeError, ValueError):
        return None
    return 1.0 / rate if rate > 0 else None


async def native_qty(ticker: str, notional_usd: float, price_native: float) -> tuple[float, float] | None:
    """(true quantity, usd_per_unit) for a USD notional at a native price."""
    if notional_usd <= 0 or price_native <= 0:
        return None
    k = await usd_per_unit(instrument_currency(ticker))
    if not k:
        return None
    return notional_usd / (price_native * k), k
