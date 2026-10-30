"""Platform Alpaca paper keys — market data only (not a live order router)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.services.trading_keys.platform_keys import alpaca_data_headers, platform_env


DATA_BARS_URL = "https://data.alpaca.markets/v2/stocks/{symbol}/bars"


def alpaca_paper_configured() -> bool:
    return bool(platform_env("ALPACA_API_KEY") and platform_env("ALPACA_SECRET_KEY"))


def alpaca_data_status() -> dict[str, Any]:
    headers = alpaca_data_headers()
    return {
        "configured": bool(headers),
        "base_trading_url": platform_env("ALPACA_BASE_URL") or "https://paper-api.alpaca.markets",
        "data_url": "https://data.alpaca.markets/v2",
        "quotes_only": True,
        "live_orders": False,
        "note": "Paper keys feed IEX/SIP quotes and bars. Apex paper fills stay local unless live unlock is set.",
    }


def fetch_daily_closes_sync(symbol: str, *, limit: int = 80) -> list[float]:
    """Blocking daily closes for engine actions. Empty if unconfigured or non-US symbol."""
    raw = (symbol or "").strip().upper().replace("-", ".")
    if not raw or "/" in raw or raw.endswith("USDT"):
        return []
    headers = alpaca_data_headers()
    if not headers:
        return []

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=max(limit * 2, 120))
    params = {
        "timeframe": "1Day",
        "start": start.strftime("%Y-%m-%dT00:00:00Z"),
        "end": end.strftime("%Y-%m-%dT23:59:59Z"),
        "limit": min(int(limit), 200),
        "adjustment": "split",
        "feed": "iex",
    }
    try:
        import httpx

        from app.core.http_proxy import httpx_client_kwargs

        url = DATA_BARS_URL.format(symbol=raw)
        with httpx.Client(**httpx_client_kwargs(foreign=True, timeout=12.0)) as client:
            resp = client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            rows = (resp.json() or {}).get("bars") or []
    except Exception:
        return []
    closes: list[float] = []
    for row in rows:
        try:
            closes.append(float(row["c"]))
        except (KeyError, TypeError, ValueError):
            continue
    return closes[-limit:]
