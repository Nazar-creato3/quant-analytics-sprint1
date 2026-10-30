"""Historical bar loaders for validation replay (Binance / MOEX / Tinkoff)."""
from __future__ import annotations

import math
import os
import random
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.core.http_proxy import httpx_client_kwargs
from app.services.integration.types import HistoricalBar
from app.services.market_data.binance_spot import get_crypto_bars

MOEX_CANDLES_URL = (
    "https://iss.moex.com/iss/engines/stock/markets/shares/securities/{ticker}/candles.json"
)

TINKOFF_LIVE_HOST = "invest-public-api.tbank.ru"
TINKOFF_SANDBOX_HOST = "sandbox-invest-public-api.tbank.ru"


def tinkoff_use_sandbox() -> bool:
    """Sandbox is only for paper *order* placement — market data always prefers live.

    Explicit TINKOFF_SANDBOX=true still routes to sandbox (tests / paper execution).
    Unset defaults to live invest-public-api.tbank.ru.
    """
    explicit = (os.getenv("TINKOFF_SANDBOX") or "").strip().lower()
    return explicit in ("1", "true", "yes", "on")


def tinkoff_rest_base() -> str:
    explicit = (os.getenv("TINKOFF_BASE_URL") or "").strip()
    if explicit:
        host = (
            explicit.replace("https://", "")
            .replace("http://", "")
            .replace(":443", "")
            .rstrip("/")
        )
        return host
    return TINKOFF_SANDBOX_HOST if tinkoff_use_sandbox() else TINKOFF_LIVE_HOST


def tinkoff_rpc(method: str) -> str:
    return (
        f"https://{tinkoff_rest_base()}/rest/tinkoff.public.invest.api.contract.v1.{method}"
    )


def tinkoff_rest_base_cached() -> str:
    """Alias kept for older imports; always re-reads env."""
    return tinkoff_rest_base()


TINKOFF_REST_BASE = TINKOFF_LIVE_HOST  # display default; call tinkoff_rest_base() at request time
TINKOFF_FIND_INSTRUMENT = (
    f"https://{TINKOFF_LIVE_HOST}/rest/tinkoff.public.invest.api.contract.v1."
    "InstrumentsService/FindInstrument"
)
TINKOFF_GET_CANDLES = (
    f"https://{TINKOFF_LIVE_HOST}/rest/tinkoff.public.invest.api.contract.v1."
    "MarketDataService/GetCandles"
)

KNOWN_GAPS: list[str] = [
    "EventRiskLayer active_lock DB path — not exercised in offline replay.",
]

# MOEX tickers commonly used in replay — FIGI cache for read-only market data.
_TINKOFF_FIGI_BY_TICKER: dict[str, str] = {
    "SBER": "BBG004730N88",
    "GAZP": "BBG004730RP0",
    "LKOH": "BBG004731032",
    "YNDX": "BBG006L8G4H1",
}


def _parse_bar_timestamp(raw: Any) -> datetime:
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    if isinstance(raw, str):
        text = raw.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    raise ValueError(f"unsupported timestamp: {raw!r}")


def _dict_to_bar(row: dict[str, Any], *, source: str, symbol: str) -> HistoricalBar:
    return HistoricalBar(
        timestamp=_parse_bar_timestamp(row["timestamp"]),
        open=float(row["open"]),
        high=float(row["high"]),
        low=float(row["low"]),
        close=float(row["close"]),
        volume=float(row.get("volume", 0.0)),
        source=source,
        symbol=symbol.upper(),
    )


def _tinkoff_token() -> str | None:
    from app.services.trading_keys.platform_keys import tinkoff_market_data_token

    return tinkoff_market_data_token()


def _money_to_float(value: dict[str, Any] | None) -> float:
    if not value:
        return 0.0
    units = int(value.get("units", 0) or 0)
    nano = int(value.get("nano", 0) or 0)
    return units + nano / 1_000_000_000


def _resolve_tinkoff_figi(symbol: str, token: str) -> str | None:
    cached = _TINKOFF_FIGI_BY_TICKER.get(symbol.upper())
    if cached:
        return cached
    try:
        with httpx.Client(**httpx_client_kwargs(foreign=False, timeout=15.0)) as client:
            resp = client.post(
                tinkoff_rpc("InstrumentsService/FindInstrument"),
                headers={"Authorization": f"Bearer {token}"},
                json={"query": symbol.upper()},
            )
            resp.raise_for_status()
            instruments = resp.json().get("instruments") or []
            for inst in instruments:
                ticker = str(inst.get("ticker", "")).upper()
                if ticker == symbol.upper():
                    return str(inst.get("figi") or "") or None
            if instruments:
                return str(instruments[0].get("figi") or "") or None
    except Exception:
        return None
    return None


def fetch_tinkoff_bars(symbol: str, *, days: int = 90) -> tuple[list[HistoricalBar], bool]:
    """Fetch daily Tinkoff Invest API candles (read-only; order placement stays disabled)."""
    token = _tinkoff_token()
    if not token:
        return generate_synthetic_bars(symbol, days=days, source="tinkoff_stub"), True

    figi = _resolve_tinkoff_figi(symbol, token)
    if not figi:
        return generate_synthetic_bars(symbol, days=days, source="tinkoff_stub"), True

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days + 5)
    body = {
        "figi": figi,
        "from": start.isoformat().replace("+00:00", "Z"),
        "to": end.isoformat().replace("+00:00", "Z"),
        "interval": "CANDLE_INTERVAL_DAY",
    }
    try:
        with httpx.Client(timeout=20.0) as client:
            resp = client.post(
                tinkoff_rpc("MarketDataService/GetCandles"),
                headers={"Authorization": f"Bearer {token}"},
                json=body,
            )
            resp.raise_for_status()
            payload = resp.json()
    except Exception:
        return generate_synthetic_bars(symbol, days=days, source="tinkoff_stub"), True

    candles = payload.get("candles") or []
    bars: list[HistoricalBar] = []
    for candle in candles:
        ts_raw = candle.get("time")
        if not ts_raw:
            continue
        ts = _parse_bar_timestamp(ts_raw)
        bars.append(
            HistoricalBar(
                timestamp=ts,
                open=_money_to_float(candle.get("open")),
                high=_money_to_float(candle.get("high")),
                low=_money_to_float(candle.get("low")),
                close=_money_to_float(candle.get("close")),
                volume=float(candle.get("volume", 0) or 0),
                source="tinkoff",
                symbol=symbol.upper(),
            )
        )
    if not bars:
        return generate_synthetic_bars(symbol, days=days, source="tinkoff_stub"), True
    return bars[-days:], False


async def fetch_binance_bars(symbol: str, *, days: int = 90) -> tuple[list[HistoricalBar], bool]:
    """Fetch daily crypto bars from Binance public API."""
    limit = min(max(days, 1), 1000)
    raw = await get_crypto_bars(symbol, "1d", limit)
    bars = [_dict_to_bar(row, source="binance", symbol=symbol) for row in raw]
    return bars[-days:], False


async def fetch_moex_bars(symbol: str, *, days: int = 90) -> tuple[list[HistoricalBar], bool]:
    """Fetch daily MOEX ISS candles; falls back to synthetic on failure."""
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=days + 5)
    params = {
        "from": start.isoformat(),
        "till": end.isoformat(),
        "interval": "24",
        "iss.meta": "off",
    }
    url = MOEX_CANDLES_URL.format(ticker=symbol.upper())
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            payload = resp.json()
    except Exception:
        return generate_synthetic_bars(symbol, days=days, source="moex_stub"), True

    candles = payload.get("candles", {})
    columns = candles.get("columns", [])
    rows = candles.get("data", [])
    if not rows:
        return generate_synthetic_bars(symbol, days=days, source="moex_stub"), True

    bars: list[HistoricalBar] = []
    for row in rows:
        record = dict(zip(columns, row))
        begin = record.get("begin")
        if not begin:
            continue
        ts = datetime.fromisoformat(str(begin).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        bars.append(
            HistoricalBar(
                timestamp=ts,
                open=float(record.get("open", 0)),
                high=float(record.get("high", 0)),
                low=float(record.get("low", 0)),
                close=float(record.get("close", 0)),
                volume=float(record.get("volume", 0)),
                source="moex",
                symbol=symbol.upper(),
            )
        )
    if not bars:
        return generate_synthetic_bars(symbol, days=days, source="moex_stub"), True
    return bars[-days:], False


def generate_synthetic_bars(
    symbol: str,
    *,
    days: int = 90,
    source: str = "synthetic",
    seed: int | None = None,
) -> list[HistoricalBar]:
    """Generate reproducible OHLCV for offline validation."""
    rng = random.Random(seed if seed is not None else hash(symbol) & 0xFFFF)
    now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    price = 100.0 + (hash(symbol) % 500)
    bars: list[HistoricalBar] = []

    for offset in range(days, 0, -1):
        ts = now - timedelta(days=offset)
        drift = rng.uniform(-0.025, 0.025)
        close = max(1.0, price * (1.0 + drift))
        high = max(close, price) * (1.0 + rng.uniform(0, 0.01))
        low = min(close, price) * (1.0 - rng.uniform(0, 0.01))
        open_price = price
        volume = rng.uniform(1_000, 50_000)
        bars.append(
            HistoricalBar(
                timestamp=ts,
                open=round(open_price, 4),
                high=round(high, 4),
                low=round(low, 4),
                close=round(close, 4),
                volume=round(volume, 2),
                source=source,
                symbol=symbol.upper(),
            )
        )
        price = close
    return bars


def rolling_indicators(closes: list[float], highs: list[float], lows: list[float]) -> dict[str, float]:
    """Compute strategy-facing indicators from trailing window."""
    if len(closes) < 2:
        return {
            "momentum": 0.0,
            "volatility": 0.12,
            "mean_reversion_z": 0.0,
            "breakout_strength": 0.0,
            "spread_bps": 8.0,
        }

    window = closes[-20:] if len(closes) >= 20 else closes
    mean = sum(window) / len(window)
    variance = sum((value - mean) ** 2 for value in window) / max(1, len(window) - 1)
    std = math.sqrt(variance) if variance > 0 else 1e-6

    lookback = min(5, len(closes) - 1)
    momentum = (closes[-1] - closes[-1 - lookback]) / max(closes[-1 - lookback], 1e-9)
    returns = [
        (closes[index] - closes[index - 1]) / max(closes[index - 1], 1e-9)
        for index in range(1, len(window))
    ]
    vol = math.sqrt(sum(value * value for value in returns) / max(1, len(returns))) * math.sqrt(252)
    mean_reversion_z = (closes[-1] - mean) / std
    recent_high = max(highs[-20:] if len(highs) >= 20 else highs)
    breakout_strength = (closes[-1] - recent_high) / max(recent_high, 1e-9)

    return {
        "momentum": round(momentum, 4),
        "volatility": round(min(1.0, max(0.01, vol)), 4),
        "mean_reversion_z": round(mean_reversion_z, 4),
        "breakout_strength": round(breakout_strength, 4),
        "spread_bps": 8.0,
    }
