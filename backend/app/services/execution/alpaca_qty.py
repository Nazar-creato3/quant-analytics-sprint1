"""Alpaca qty vs notional. Do not invent a USD size or truncate shares."""
from __future__ import annotations


def alpaca_order_qty_fields(qty: float, limit_price: float | None) -> dict[str, float | str]:
    if qty <= 0:
        raise ValueError("нет данных")
    if qty < 1:
        if limit_price is None or limit_price <= 0:
            raise ValueError("нет данных")
        return {"notional": round(qty * limit_price, 2)}
    return {"qty": str(qty)}
