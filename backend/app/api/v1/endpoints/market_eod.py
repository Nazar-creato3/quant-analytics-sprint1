"""EOD / licensed quote envelope and chart indicators (Prompt 04 / 42)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.services.market_data.indicators import overlays_from_bars
from app.services.market_data.license import quote_envelope

router = APIRouter(prefix="/market", tags=["market"])


@router.get("/quote-envelope")
def quote_envelope_endpoint(
    symbol: str = Query(..., min_length=1),
    source: str = Query("iss_moex"),
    price: str | None = Query(None),
    as_of: str = Query("2024-01-31"),
    audience: str = Query("internal"),
    delayed: bool = Query(True),
    delay_minutes: int = Query(15, ge=0, le=10080),
) -> dict:
    """License wrapper only. Does not fetch a market quote; missing price stays empty."""
    aud = audience if audience in {"owner", "public", "internal"} else "internal"
    shown = price.strip() if isinstance(price, str) and price.strip() else None
    return quote_envelope(
        symbol=symbol,
        price=shown,
        source=source,
        as_of=as_of,
        delayed=delayed,
        audience=aud,  # type: ignore[arg-type]
        delay_minutes=delay_minutes,
        trusted_price=False,
    )


class IndicatorBarsIn(BaseModel):
    bars: list[dict[str, Any]] = Field(default_factory=list)
    ticker: str = ""
    timeframe: str = "1d"


@router.post("/indicators")
def chart_indicators(body: IndicatorBarsIn) -> dict:
    if not body.bars:
        return {"overlays": {}, "freshness_label": "нет данных"}
    return {"overlays": overlays_from_bars(body.bars), "freshness_label": "в реальном времени"}
