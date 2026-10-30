"""Fundamentals and technical indicators for cockpit / quote APIs."""
from __future__ import annotations

import asyncio
from typing import Any, Sequence

from app.core.logging import get_logger
from app.utils.json_safe import sanitize_for_json
from app.services.control_fabric.risk_gate import compute_atr
from app.services.market_data.moex_spot import (
    is_moex_ticker,
    normalize_moex_symbol,
    to_yfinance_symbol,
)

logger = get_logger(__name__)


def _ema(values: Sequence[float], period: int) -> float | None:
    if len(values) < period or period <= 0:
        return None
    alpha = 2 / (period + 1)
    ema = sum(values[:period]) / period
    for value in values[period:]:
        ema = alpha * value + (1 - alpha) * ema
    return ema


def _rsi(closes: Sequence[float], period: int = 14) -> float | None:
    if len(closes) <= period:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for idx in range(1, len(closes)):
        delta = closes[idx] - closes[idx - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    if len(gains) < period:
        return None
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def compute_technicals_from_bars(bars: Sequence[Any]) -> dict[str, Any]:
    """Derive RSI/MACD/ATR/52-week range from stored OHLCV bars."""
    if not bars:
        return {}

    closes = [float(b.close) for b in bars if getattr(b, "close", None) is not None]
    highs = [float(b.high) for b in bars if getattr(b, "high", None) is not None]
    lows = [float(b.low) for b in bars if getattr(b, "low", None) is not None]
    volumes = [float(b.volume or 0) for b in bars]

    technical: dict[str, Any] = {}
    if closes:
        technical["rsi"] = _rsi(closes)
        ema12 = _ema(closes, 12)
        ema26 = _ema(closes, 26)
        if ema12 is not None and ema26 is not None:
            technical["macd"] = round(ema12 - ema26, 4)
    if highs and lows and closes and len(closes) >= 15:
        atr = compute_atr(highs[-60:], lows[-60:], closes[-60:])
        if atr > 0:
            technical["atr"] = round(atr, 4)
    if volumes:
        technical["avg_volume"] = round(sum(volumes[-20:]) / min(20, len(volumes)), 0)
    if len(closes) >= 20:
        window = closes[-252:] if len(closes) >= 252 else closes
        technical["week52_low"] = round(min(window), 2)
        technical["week52_high"] = round(max(window), 2)
    return sanitize_for_json({k: v for k, v in technical.items() if v is not None})


def _fetch_yfinance_info_sync(symbol: str) -> dict[str, Any]:
    import yfinance as yf

    ticker = yf.Ticker(symbol.upper())
    info = ticker.info or {}
    return {
        "market_cap": info.get("marketCap"),
        "pe_ratio": info.get("trailingPE") or info.get("forwardPE"),
        "eps": info.get("trailingEps"),
        "dividend_yield": info.get("dividendYield"),
        "roe": info.get("returnOnEquity"),
        "roa": info.get("returnOnAssets"),
        "beta": info.get("beta"),
        "fiftyTwoWeekRange": info.get("fiftyTwoWeekRange"),
        "averageVolume": info.get("averageVolume") or info.get("averageDailyVolume10Day"),
    }


def _merge_fundamentals(primary: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    """Prefer primary values; fill gaps from fallback."""
    merged = dict(fallback)
    merged.update({k: v for k, v in primary.items() if v is not None})
    if primary.get("source"):
        merged["source"] = primary["source"]
    return merged


async def _fetch_yfinance_fundamentals(symbol: str) -> dict[str, Any]:
    lookup = to_yfinance_symbol(symbol) if is_moex_ticker(symbol) else symbol.upper()
    try:
        raw = await asyncio.wait_for(
            asyncio.to_thread(_fetch_yfinance_info_sync, lookup),
            timeout=3.0,
        )
    except asyncio.TimeoutError:
        logger.debug("Fundamentals yfinance timed out", symbol=lookup)
        return {}
    except Exception as exc:
        logger.debug("Fundamentals fetch failed", symbol=lookup, error=str(exc))
        return {}
    if is_moex_ticker(symbol):
        raw.setdefault("exchange", "MOEX")
        raw.setdefault("symbol", normalize_moex_symbol(symbol))
        raw.setdefault("source", "yfinance")
    else:
        raw.setdefault("source", "yfinance")
    return sanitize_for_json({k: v for k, v in raw.items() if v is not None})


async def fetch_fundamentals(symbol: str) -> dict[str, Any]:
    """Load fundamentals: MOEX ISS / FMP primary, yfinance fallback."""
    raw: dict[str, Any] = {}

    if is_moex_ticker(symbol):
        from app.services.market_data.moex_iss_provider import (
            fetch_moex_dividends,
            fetch_moex_fundamentals,
        )

        raw = await fetch_moex_fundamentals(symbol)
        if not raw.get("market_cap"):
            yf = await _fetch_yfinance_fundamentals(symbol)
            raw = _merge_fundamentals(raw, yf)
        if raw.get("dividend_yield") is None:
            div_payload = await fetch_moex_dividends(symbol)
            if div_payload.get("dividend_yield") is not None:
                raw["dividend_yield"] = div_payload["dividend_yield"]
            if div_payload.get("dividends"):
                raw["dividend_history"] = div_payload["dividends"]
        if not raw:
            return {
                "note": "MOEX fundamentals unavailable from ISS and yfinance",
                "exchange": "MOEX",
                "symbol": normalize_moex_symbol(symbol),
            }
        raw.setdefault("exchange", "MOEX")
        raw.setdefault("symbol", normalize_moex_symbol(symbol))
    else:
        from app.services.market_data.fmp_provider import fetch_fmp_fundamentals

        raw = await fetch_fmp_fundamentals(symbol)
        if not raw.get("market_cap") and not raw.get("pe_ratio"):
            yf = await _fetch_yfinance_fundamentals(symbol)
            raw = _merge_fundamentals(raw, yf)
        if not raw:
            raw = await _fetch_yfinance_fundamentals(symbol)

    return sanitize_for_json({k: v for k, v in raw.items() if v is not None})


async def enrich_symbol_metadata(
    symbol: str,
    bars: Sequence[Any] | None = None,
) -> dict[str, Any]:
    """Build metadata.fundamentals + metadata.technical for cockpit consumers."""
    technical = compute_technicals_from_bars(bars or [])
    fundamentals = await fetch_fundamentals(symbol)

    if fundamentals.get("beta") is None and technical.get("beta") is None:
        pass
    elif fundamentals.get("beta") is not None and "beta" not in technical:
        technical.setdefault("beta", fundamentals.get("beta"))

    metadata: dict[str, Any] = {}
    if fundamentals:
        metadata["fundamentals"] = fundamentals
    if technical:
        metadata["technical"] = technical
    return sanitize_for_json(metadata)
