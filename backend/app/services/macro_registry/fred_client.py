"""Shared FRED API helpers with US/Canada key routing."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

import httpx

from app.core.config import settings
from app.services.macro_registry.adapters.base import http_get_with_retry

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
FredRegion = Literal["us", "canada"]


def resolve_fred_api_key(region: FredRegion = "us") -> str:
    """Return the API key for the requested FRED region."""
    if region == "canada":
        key = settings.FRED_CANADA_API_KEY.strip()
        if not key:
            raise RuntimeError("FRED_CANADA_API_KEY not configured")
        return key
    key = settings.FRED_API_KEY.strip()
    if not key:
        raise RuntimeError("FRED_API_KEY not configured")
    return key


def parse_fred_endpoint(endpoint: str) -> tuple[FredRegion, str] | None:
    """Parse adapter:fred:* or adapter:fred_ca:* endpoints."""
    if endpoint.startswith("adapter:fred_ca:"):
        return "canada", endpoint.split(":", 2)[2]
    if endpoint.startswith("adapter:fred:"):
        return "us", endpoint.split(":", 2)[2]
    return None


async def fetch_fred_series_json(
    client: httpx.AsyncClient,
    series_id: str,
    *,
    region: FredRegion = "us",
    lookback_days: int = 365,
    vintage: bool = False,
) -> str:
    """Fetch FRED observations. vintage=True keeps ALFRED realtime_start/end (look-ahead ban)."""
    start = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    params = {
        "series_id": series_id,
        "api_key": resolve_fred_api_key(region),
        "file_type": "json",
        "observation_start": start,
        "sort_order": "asc",
        "limit": "100000",
    }
    if vintage:
        # All vintages from ALFRED. Default FRED call is *current* revision only.
        params["realtime_start"] = "1776-07-04"
    response = await http_get_with_retry(client, FRED_BASE, params=params)
    return response.text
