"""Market data helpers via CCXT (primary) with optional CryptoDataPy / TA."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _ccxt_exchange(exchange_id: str = "binance"):
    import ccxt

    exchange_id = exchange_id.lower().strip()
    cls = getattr(ccxt, exchange_id, None)
    if cls is None:
        raise ValueError(f"unknown exchange: {exchange_id}")
    return cls({"enableRateLimit": True, "options": {"defaultType": "spot"}})


def _binance_public():
    return _ccxt_exchange("binance")


def fetch_ticker(symbol: str = "BTC/USDT") -> dict[str, Any]:
    """Public Binance ticker via CCXT."""
    exchange = _binance_public()
    raw = exchange.fetch_ticker(symbol)
    return {
        "symbol": symbol,
        "provider": "ccxt.binance",
        "last": raw.get("last"),
        "bid": raw.get("bid"),
        "ask": raw.get("ask"),
        "high": raw.get("high"),
        "low": raw.get("low"),
        "base_volume": raw.get("baseVolume"),
        "quote_volume": raw.get("quoteVolume"),
        "percentage": raw.get("percentage"),
        "timestamp": raw.get("timestamp"),
        "datetime": raw.get("datetime"),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def fetch_ohlcv(
    symbol: str = "BTC/USDT",
    timeframe: str = "1h",
    limit: int = 50,
) -> dict[str, Any]:
    """Public OHLCV candles via CCXT."""
    exchange = _binance_public()
    rows = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    candles = [
        {
            "ts": int(r[0]),
            "open": r[1],
            "high": r[2],
            "low": r[3],
            "close": r[4],
            "volume": r[5],
        }
        for r in rows
    ]
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "provider": "ccxt.binance",
        "count": len(candles),
        "candles": candles,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def ta_snapshot(symbol: str = "BTC/USDT", timeframe: str = "1h", limit: int = 100) -> dict[str, Any]:
    """Lightweight TA snapshot from CCXT OHLCV (SMA/EMA/RSI).

    Uses pandas if available; does not require crypto-powerdata-mcp in-process
    (that package is primarily an MCP server process).
    """
    data = fetch_ohlcv(symbol=symbol, timeframe=timeframe, limit=limit)
    candles = data["candles"]
    if len(candles) < 20:
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "ok": False,
            "error": "insufficient_candles",
            "count": len(candles),
        }

    try:
        import pandas as pd
    except ImportError:
        closes = [c["close"] for c in candles]
        last = closes[-1]
        sma20 = sum(closes[-20:]) / 20
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "ok": True,
            "last": last,
            "sma20": sma20,
            "engine": "stdlib",
            "fetched_at": data["fetched_at"],
        }

    df = pd.DataFrame(candles)
    close = df["close"].astype(float)
    sma20 = float(close.tail(20).mean())
    sma50 = float(close.tail(50).mean()) if len(close) >= 50 else None
    ema12 = float(close.ewm(span=12, adjust=False).mean().iloc[-1])
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, float("nan"))
    rsi_series = 100 - (100 / (1 + rs))
    rsi_val = rsi_series.iloc[-1]
    rsi = None if rsi_val != rsi_val else float(rsi_val)  # NaN check

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "ok": True,
        "last": float(close.iloc[-1]),
        "sma20": sma20,
        "sma50": sma50,
        "ema12": ema12,
        "rsi14": rsi,
        "engine": "pandas",
        "count": len(candles),
        "fetched_at": data["fetched_at"],
    }


def cryptodatapy_status() -> dict[str, Any]:
    """Probe CryptoDataPy without requiring API keys for a full pull."""
    try:
        import cryptodatapy  # noqa: F401

        version = getattr(cryptodatapy, "__version__", "unknown")
        return {"available": True, "version": version}
    except Exception as exc:  # noqa: BLE001
        from app.core.logging import get_logger

        get_logger(__name__).warning("cryptodatapy probe failed", error=str(exc))
        return {"available": False, "error": "нет данных"}
