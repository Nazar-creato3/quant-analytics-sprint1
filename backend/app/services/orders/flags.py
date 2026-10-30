"""Order ticket guards: post-only, reduce-only, per-venue TIF."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Side = Literal["buy", "sell"]


class OrderFlagError(ValueError):
    """Client-side order validation failure before venue submit."""


@dataclass(frozen=True, slots=True)
class BookTop:
    best_bid: float | None = None
    best_ask: float | None = None


def limit_would_take(*, side: Side, limit_price: float, book: BookTop) -> bool:
    if side == "buy":
        return book.best_ask is not None and limit_price >= book.best_ask
    return book.best_bid is not None and limit_price <= book.best_bid


def validate_post_only(
    *,
    post_only: bool,
    order_type: str,
    side: Side,
    limit_price: float | None,
    book: BookTop | None,
) -> None:
    if not post_only:
        return
    if order_type not in ("limit", "stop_limit"):
        return
    if book is None:
        return
    if limit_price is None:
        raise OrderFlagError("Post-Only: укажите limit price")
    if limit_would_take(side=side, limit_price=limit_price, book=book):
        raise OrderFlagError("Post-Only: ордер пересёк бы спред и исполнился как тейкер")


def validate_reduce_only(
    *,
    reduce_only: bool,
    side: Side,
    quantity: float,
    position_qty: float | None,
    position_side: str | None,
) -> None:
    if not reduce_only:
        return
    if position_qty is None or position_side is None or position_qty <= 0:
        raise OrderFlagError("Reduce-Only: нет открытой позиции для уменьшения")
    if position_side == "long" and side == "buy":
        raise OrderFlagError("Reduce-Only: нельзя перевернул long покупкой")
    if position_side == "short" and side == "sell":
        raise OrderFlagError("Reduce-Only: нельзя перевернул short продажей")
    if quantity > position_qty + 1e-12:
        raise OrderFlagError(f"Reduce-Only: размер {quantity} больше позиции {position_qty}")


def validate_tif(tif: str, venue: str | None) -> str:
    from app.services.orders.venue_capabilities import tif_for_venue

    normalized = (tif or "gtc").lower()
    allowed = tif_for_venue(venue)
    if normalized not in allowed:
        raise OrderFlagError(f"TIF {tif.upper()} недоступен для {venue or 'venue'}")
    return normalized
