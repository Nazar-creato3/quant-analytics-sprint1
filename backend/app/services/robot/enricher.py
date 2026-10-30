"""Market data enricher — L2 snapshots, tape, heuristic regime, simple signal ensemble."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import OHLCVBar, new_uuid
from app.db.robot_models import OrderbookSnapshot, TapeEvent

logger = get_logger(__name__)


async def store_orderbook(
    db: AsyncSession,
    *,
    ticker: str,
    bids: list[list[float]],
    asks: list[list[float]],
    venue: str = "paper",
) -> OrderbookSnapshot:
    mid = None
    spread_bps = None
    if bids and asks and bids[0] and asks[0]:
        bid = float(bids[0][0])
        ask = float(asks[0][0])
        mid = (bid + ask) / 2.0
        if mid > 0:
            spread_bps = (ask - bid) / mid * 10000.0
    snap = OrderbookSnapshot(
        id=new_uuid(),
        ticker=ticker.strip().upper(),
        venue=venue,
        bids=bids,
        asks=asks,
        mid=mid,
        spread_bps=spread_bps,
        captured_at=datetime.now(timezone.utc),
    )
    db.add(snap)
    await db.flush()
    return snap


async def store_tape(
    db: AsyncSession,
    *,
    ticker: str,
    price: float,
    qty: float,
    side: str = "buy",
    venue: str = "paper",
) -> TapeEvent:
    ev = TapeEvent(
        id=new_uuid(),
        ticker=ticker.strip().upper(),
        venue=venue,
        price=float(price),
        qty=float(qty),
        side=side,
        occurred_at=datetime.now(timezone.utc),
    )
    db.add(ev)
    await db.flush()
    return ev


def detect_regime(closes: Sequence[float]) -> str:
    """Heuristic regime: trend_up | trend_down | range | volatile."""
    if len(closes) < 10:
        return "range"
    xs = [float(c) for c in closes if c and c > 0]
    if len(xs) < 10:
        return "range"
    rets = [(xs[i] / xs[i - 1] - 1.0) for i in range(1, len(xs))]
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / max(len(rets) - 1, 1)
    vol = var ** 0.5
    drift = xs[-1] / xs[0] - 1.0
    if vol > 0.03:
        return "volatile"
    if drift > 0.02 and mean > 0:
        return "trend_up"
    if drift < -0.02 and mean < 0:
        return "trend_down"
    return "range"


def ensemble_signal(closes: Sequence[float]) -> dict[str, Any]:
    """Weighted blend of trend, mean-reversion and momentum computed from closes."""
    if len(closes) < 5:
        return {"signal": 0.0, "regime": "range", "components": {}}
    xs = [float(c) for c in closes]
    regime = detect_regime(xs)
    # trend: slope of last N
    trend = (xs[-1] / xs[0] - 1.0)
    # mean reversion: distance from SMA
    sma = sum(xs) / len(xs)
    mr = (sma - xs[-1]) / sma if sma else 0.0
    # momentum: last 3 vs prior 3
    if len(xs) >= 6:
        mom = (sum(xs[-3:]) / 3.0) / (sum(xs[-6:-3]) / 3.0) - 1.0
    else:
        mom = 0.0
    weights = {"trend": 0.4, "mean_reversion": 0.3, "momentum": 0.3}
    signal = weights["trend"] * trend + weights["mean_reversion"] * mr + weights["momentum"] * mom
    return {
        "signal": round(signal, 6),
        "regime": regime,
        "components": {
            "trend": round(trend, 6),
            "mean_reversion": round(mr, 6),
            "momentum": round(mom, 6),
        },
    }


async def enrich_ticker(db: AsyncSession, *, ticker: str, lookback: int = 60) -> dict[str, Any]:
    """Pull recent OHLCV and compute regime/ensemble. Never invent L2 or tape (GA16-317)."""
    sym = ticker.strip().upper()
    stmt = (
        select(OHLCVBar)
        .where(OHLCVBar.ticker == sym)
        .order_by(OHLCVBar.timestamp.desc())
        .limit(lookback)
    )
    result = await db.execute(stmt)
    bars = list(reversed(result.scalars().all()))
    closes = [float(b.close) for b in bars if b.close]
    ens = ensemble_signal(closes)
    logger.info("market_enriched", ticker=sym, regime=ens.get("regime"))
    return {"ticker": sym, "bars": len(closes), **ens}
