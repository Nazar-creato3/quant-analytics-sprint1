"""LOB-derived microstructure features from real order book depth."""
from __future__ import annotations

from dataclasses import dataclass

from app.schemas.orders import OrderBookLevel, OrderBookSnapshot


@dataclass(frozen=True, slots=True)
class LobFeatureVector:
    order_flow_imbalance: float
    bid_ask_spread_bps: float
    depth_weighted_mid: float
    depth_available: bool

    def to_dict(self) -> dict[str, float | bool]:
        return {
            "order_flow_imbalance": self.order_flow_imbalance,
            "bid_ask_spread_bps": self.bid_ask_spread_bps,
            "depth_weighted_mid": self.depth_weighted_mid,
            "depth_available": self.depth_available,
        }


def _depth_weighted_price(levels: list[OrderBookLevel], *, side: str) -> float:
    if not levels:
        return 0.0
    total_size = sum(l.size for l in levels if l.size > 0)
    if total_size <= 0:
        return 0.0
    weighted = sum(l.price * l.size for l in levels if l.size > 0)
    return weighted / total_size


def lob_features_from_snapshot(book: OrderBookSnapshot) -> LobFeatureVector:
    """Standard LOB features — never fabricate depth when unavailable."""
    if not book.depth_available or (not book.bids and not book.asks):
        return LobFeatureVector(
            order_flow_imbalance=0.0,
            bid_ask_spread_bps=float(book.spread_bps or 0.0),
            depth_weighted_mid=float(book.mid_price or 0.0),
            depth_available=False,
        )

    bid_vol = sum(b.size for b in book.bids if b.size > 0)
    ask_vol = sum(a.size for a in book.asks if a.size > 0)
    denom = bid_vol + ask_vol
    imbalance = (bid_vol - ask_vol) / denom if denom > 0 else 0.0

    bid_w = _depth_weighted_price(book.bids, side="bid")
    ask_w = _depth_weighted_price(book.asks, side="ask")
    if bid_w > 0 and ask_w > 0:
        depth_mid = (bid_w * ask_vol + ask_w * bid_vol) / denom if denom > 0 else (bid_w + ask_w) / 2.0
    else:
        depth_mid = float(book.mid_price or 0.0)

    return LobFeatureVector(
        order_flow_imbalance=round(imbalance, 6),
        bid_ask_spread_bps=float(book.spread_bps or 0.0),
        depth_weighted_mid=round(depth_mid, 6),
        depth_available=True,
    )
