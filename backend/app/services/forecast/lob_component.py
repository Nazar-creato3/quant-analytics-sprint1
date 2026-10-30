"""LOB microstructure ensemble component with adaptive walk-forward accuracy."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from app.core.logging import get_logger
from app.schemas.orders import OrderBookSnapshot
from app.services.forecast.lob_features import lob_features_from_snapshot

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class LobForecastResult:
    expected_return: float
    direction: int
    available: bool
    recent_accuracy: float
    note: str = ""
    features: dict[str, float | bool] | None = None


def _sign(ret: float, threshold: float = 0.002) -> int:
    if ret > threshold:
        return 1
    if ret < -threshold:
        return -1
    return 0


class LobMicrostructureComponent:
    """Direction signal from order-flow imbalance and spread dynamics."""

    def predict(
        self,
        book: OrderBookSnapshot | None,
        *,
        horizon: int = 10,
        prior_imbalance: float = 0.0,
    ) -> LobForecastResult:
        if book is None:
            return LobForecastResult(0.0, 0, False, 0.5, "no_order_book")

        feats = lob_features_from_snapshot(book)
        if not feats.depth_available:
            return LobForecastResult(
                0.0,
                0,
                False,
                0.5,
                book.depth_unavailable_reason or "depth_unavailable",
                features=feats.to_dict(),
            )

        imbalance = feats.order_flow_imbalance
        spread_bps = feats.bid_ask_spread_bps
        spread_penalty = max(0.25, 1.0 - min(spread_bps, 100.0) / 200.0)
        magnitude = abs(imbalance) * spread_penalty * 0.04
        direction = _sign(imbalance)
        ret = direction * magnitude * (horizon / 10.0)
        return LobForecastResult(
            ret,
            direction,
            True,
            0.5,
            f"lob_imbalance:{imbalance:.3f}",
            features=feats.to_dict(),
        )

    def predict_from_imbalance(
        self,
        imbalance: float,
        *,
        spread_bps: float = 0.0,
        horizon: int = 10,
    ) -> LobForecastResult:
        """Lightweight LOB signal when only imbalance/spread features are available."""
        if abs(imbalance) < 1e-6 and spread_bps <= 0:
            return LobForecastResult(0.0, 0, False, 0.5, "no_lob_features")
        spread_penalty = max(0.25, 1.0 - min(spread_bps, 100.0) / 200.0)
        magnitude = abs(imbalance) * spread_penalty * 0.04
        direction = _sign(imbalance)
        ret = direction * magnitude * (horizon / 10.0)
        return LobForecastResult(
            ret,
            direction,
            True,
            0.5,
            f"lob_proxy:{imbalance:.3f}",
            features={
                "order_flow_imbalance": imbalance,
                "bid_ask_spread_bps": spread_bps,
                "depth_available": False,
            },
        )

    def rolling_accuracy(
        self,
        prices: Sequence[float],
        *,
        imbalance_series: Sequence[float] | None = None,
        horizon: int = 5,
        window: int = 20,
    ) -> float:
        """Walk-forward accuracy using historical imbalance proxy when LOB history sparse."""
        if len(prices) < window + horizon + 5:
            return 0.5
        hits = total = 0
        for i in range(window, len(prices) - horizon):
            if imbalance_series and i < len(imbalance_series):
                imb = float(imbalance_series[i])
            else:
                ret5 = (prices[i] - prices[i - 5]) / max(prices[i - 5], 1e-9) if i >= 5 else 0.0
                imb = max(-1.0, min(1.0, ret5 * 20.0))
            pred_dir = _sign(imb)
            if pred_dir == 0:
                continue
            actual = (prices[i + horizon] - prices[i]) / max(prices[i], 1e-9)
            if _sign(actual) == pred_dir:
                hits += 1
            total += 1
        return hits / total if total else 0.5


_component: LobMicrostructureComponent | None = None


def get_lob_component() -> LobMicrostructureComponent:
    global _component
    if _component is None:
        _component = LobMicrostructureComponent()
    return _component
