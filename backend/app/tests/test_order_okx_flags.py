"""OKX-level order ticket guards: post-only, reduce-only, per-venue TIF."""
from __future__ import annotations

import pytest

from app.services.orders.flags import (
    BookTop,
    OrderFlagError,
    limit_would_take,
    validate_post_only,
    validate_reduce_only,
    validate_tif,
)
from app.services.orders.venue_capabilities import leverage_supported, tif_for_venue


def test_limit_would_take_buy_crosses_ask():
    book = BookTop(best_bid=100.0, best_ask=101.0)
    assert limit_would_take(side="buy", limit_price=101.0, book=book)
    assert not limit_would_take(side="buy", limit_price=100.5, book=book)


def test_post_only_rejects_crossing_limit():
    book = BookTop(best_bid=100.0, best_ask=101.0)
    with pytest.raises(OrderFlagError, match="тейкер"):
        validate_post_only(
            post_only=True,
            order_type="limit",
            side="buy",
            limit_price=101.0,
            book=book,
        )


def test_post_only_allows_maker_limit():
    book = BookTop(best_bid=100.0, best_ask=101.0)
    validate_post_only(
        post_only=True,
        order_type="limit",
        side="buy",
        limit_price=100.5,
        book=book,
    )


def test_reduce_only_rejects_flip():
    with pytest.raises(OrderFlagError, match="перевернул"):
        validate_reduce_only(
            reduce_only=True,
            side="buy",
            quantity=1.0,
            position_qty=2.0,
            position_side="long",
        )


def test_reduce_only_caps_quantity():
    with pytest.raises(OrderFlagError, match="больше позиции"):
        validate_reduce_only(
            reduce_only=True,
            side="sell",
            quantity=3.0,
            position_qty=2.0,
            position_side="long",
        )


def test_tif_binance_hides_day():
    assert "day" not in tif_for_venue("binance")
    with pytest.raises(OrderFlagError, match="DAY"):
        validate_tif("day", "binance")
    assert validate_tif("ioc", "binance") == "ioc"


def test_leverage_not_faked_for_spot_venues():
    assert leverage_supported("binance") is False
    assert leverage_supported("alpaca") is False
    assert leverage_supported(None) is False
