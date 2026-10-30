"""Binance quantity fields. Do not invent a price or bump notional."""
from __future__ import annotations

_MIN_QUOTE_NOTIONAL = 10.0


def binance_order_qty_params(qty: float, limit_price: float | None) -> dict[str, str]:
    if qty >= 1:
        return {"quantity": str(round(qty, 8))}
    if limit_price is None or limit_price <= 0:
        raise ValueError("нет данных")
    notional = qty * limit_price
    if notional < _MIN_QUOTE_NOTIONAL:
        raise ValueError("нет данных")
    return {"quoteOrderQty": str(round(notional, 2))}
