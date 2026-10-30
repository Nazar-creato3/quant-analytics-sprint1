"""
Batch yfinance / FMP enrichment — one download for many symbols.

Avoids ProviderRouter rate-limit storms that leave change_pct null in Terminal UI.
Never invents 0.00 for missing prices; missing → omit field / no_data upstream.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)
FMP_BASE = "https://financialmodelingprep.com/api/v3"

# Liquid US + ETF + crypto universe for pulse movers / breadth estimate
PULSE_MOVER_UNIVERSE: tuple[str, ...] = (
    "AAPL",
    "MSFT",
    "NVDA",
    "GOOGL",
    "AMZN",
    "META",
    "TSLA",
    "AMD",
    "NFLX",
    "AVGO",
    "JPM",
    "XOM",
    "SPY",
    "QQQ",
    "IWM",
    "GLD",
    "SLV",
    "TLT",
    "BTC-USD",
    "ETH-USD",
)


def _finite(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


def _yf_batch_sync(symbols: list[str], *, period: str = "1y") -> dict[str, dict[str, Any]]:
    """
    Single yfinance download → per-symbol:
      price, change_pct (vs prev close), week/month/ytd_change_pct, atr, vol_atr, trend, regime
    """
    import yfinance as yf

    out: dict[str, dict[str, Any]] = {}
    if not symbols:
        return out
    uniq = list(dict.fromkeys(s.strip() for s in symbols if s and s.strip()))
    try:
        data = yf.download(
            uniq,
            period=period,
            interval="1d",
            group_by="ticker",
            auto_adjust=True,
            threads=True,
            progress=False,
        )
    except Exception as exc:
        logger.warning("yf batch download failed", error=str(exc), n=len(uniq))
        return out

    if data is None or getattr(data, "empty", True):
        return out

    year = datetime.now(timezone.utc).year

    def _frame_for(sym: str):
        # Multi-ticker: columns MultiIndex (ticker, OHLCV); single: flat columns
        try:
            if hasattr(data.columns, "levels") and len(getattr(data.columns, "levels", [])) >= 2:
                if sym not in data.columns.get_level_values(0):
                    return None
                return data[sym].dropna(how="all")
            # single symbol download
            if len(uniq) == 1:
                return data.dropna(how="all")
        except Exception:
            return None
        return None

    for sym in uniq:
        try:
            frame = _frame_for(sym)
            if frame is None or frame.empty or "Close" not in frame.columns:
                continue
            closes = [_finite(x) for x in frame["Close"].tolist()]
            closes = [c for c in closes if c is not None]
            if len(closes) < 2:
                continue
            highs = [_finite(x) for x in frame["High"].tolist()] if "High" in frame.columns else []
            lows = [_finite(x) for x in frame["Low"].tolist()] if "Low" in frame.columns else []
            highs = [h for h in highs if h is not None]
            lows = [lo for lo in lows if lo is not None]

            last = closes[-1]
            prev = closes[-2]
            change_pct = round((last / prev - 1.0) * 100.0, 4) if prev else None
            change = round(last * change_pct / 100.0, 6) if change_pct is not None else None

            def pct_lookback(n: int) -> Optional[float]:
                if len(closes) <= n:
                    return None
                old = closes[-(n + 1)]
                if not old:
                    return None
                return round((last / old - 1.0) * 100.0, 4)

            week = pct_lookback(5)
            month = pct_lookback(21)

            ytd = None
            try:
                for ts, row in frame.iterrows():
                    try:
                        y = int(getattr(ts, "year", None) or str(ts)[:4])
                    except Exception:
                        continue
                    if y == year:
                        c = _finite(row.get("Close"))
                        if c is not None:
                            ytd = round((last / c - 1.0) * 100.0, 4)
                            break
            except Exception:
                ytd = None

            atr = vol_atr = None
            if len(highs) >= 15 and len(lows) >= 15 and len(closes) >= 15:
                trs: list[float] = []
                n = min(len(closes), len(highs), len(lows))
                for i in range(1, n):
                    tr = max(
                        highs[i] - lows[i],
                        abs(highs[i] - closes[i - 1]),
                        abs(lows[i] - closes[i - 1]),
                    )
                    trs.append(tr)
                if len(trs) >= 14:
                    atr = round(sum(trs[-14:]) / 14.0, 6)
                    if last:
                        vol_atr = round(atr / last * 100.0, 4)

            trend = None
            if len(closes) >= 20:
                sma = sum(closes[-20:]) / 20.0
                if last > sma * 1.01:
                    trend = "up"
                elif last < sma * 0.99:
                    trend = "down"
                else:
                    trend = "sideways"

            regime = None
            if len(closes) >= 21:
                import statistics

                rets = [(closes[i] / closes[i - 1] - 1.0) for i in range(-20, 0) if closes[i - 1]]
                if len(rets) >= 10:
                    vol = statistics.pstdev(rets) * (252**0.5)
                    if vol < 0.15:
                        regime = "low_vol"
                    elif vol < 0.30:
                        regime = "normal"
                    else:
                        regime = "high_vol"

            out[sym] = {
                "symbol": sym,
                "status": "ok",
                "price": last,
                "change": change,
                "change_pct": change_pct,
                "week_change_pct": week,
                "month_change_pct": month,
                "ytd_change_pct": ytd,
                "atr": atr,
                "vol_atr": vol_atr,
                "trend": trend,
                "regime": regime,
                "provider": "yfinance_batch",
                "as_of": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as exc:
            logger.debug("yf batch symbol failed", symbol=sym, error=str(exc))
    return out


async def batch_yf_enrich(symbols: list[str], *, period: str = "1y", timeout_s: float = 5.0) -> dict[str, dict[str, Any]]:
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_yf_batch_sync, symbols, period=period),
            timeout=timeout_s,
        )
    except asyncio.TimeoutError:
        logger.warning("yf batch enrich timed out", n=len(symbols), timeout_s=timeout_s)
        return {}
    except Exception as exc:
        logger.warning("yf batch enrich failed", error=str(exc), n=len(symbols))
        return {}


async def batch_fmp_quotes(symbols: list[str], *, timeout_s: float = 4.0) -> dict[str, dict[str, Any]]:
    """FMP multi-quote — fills price + changesPercentage when keyed."""
    key = (settings.FMP_API_KEY or "").strip()
    if not key or not symbols:
        return {}
    uniq = list(dict.fromkeys(s.strip().upper() for s in symbols if s and s.strip()))
    # FMP uses plain tickers; strip ^ for indices where possible
    # Never proxy ^VIX → VIXY — ETF daily % ≠ VIX index % (causes panel mismatch).
    fmp_map = {
        "^GSPC": "SPY",  # proxy if index blocked
        "^NDX": "QQQ",
        "^DJI": "DIA",
        "^RUT": "IWM",
    }
    fmp_skip = {"^VIX"}
    # Prefer direct index symbols FMP may support
    req: list[str] = []
    rev: dict[str, str] = {}
    for s in uniq:
        if s in fmp_skip:
            continue
        fs = fmp_map.get(s, s.lstrip("^").replace("-USD", "USD") if False else s)
        # Keep crypto as BTCUSD style for FMP
        if s.endswith("-USD"):
            fs = s.replace("-USD", "USD")
        if s.startswith("^"):
            # try bare then ETF proxy
            fs = s  # FMP often wants %5EGSPC encoded — use httpx params
        req.append(fs)
        rev[fs] = s
    out: dict[str, dict[str, Any]] = {}
    try:
        chunk = ",".join(req[:40])
        from app.core.http_proxy import httpx_client_kwargs

        async with httpx.AsyncClient(
            **httpx_client_kwargs(foreign=True, timeout=httpx.Timeout(timeout_s, connect=min(3.0, timeout_s)))
        ) as client:
            resp = await client.get(
                f"{FMP_BASE}/quote/{chunk}",
                params={"apikey": key},
            )
            if resp.status_code >= 400:
                # retry with ETF proxies for indices
                proxied = []
                rev2: dict[str, str] = {}
                for s in uniq:
                    if s in fmp_skip:
                        continue
                    fs = fmp_map.get(s, s.lstrip("^"))
                    if s.endswith("-USD"):
                        fs = s.replace("-USD", "USD")
                    proxied.append(fs)
                    rev2[fs] = s
                resp = await client.get(
                    f"{FMP_BASE}/quote/{','.join(proxied[:40])}",
                    params={"apikey": key},
                )
                rev = rev2
            resp.raise_for_status()
            data = resp.json()
        if not isinstance(data, list):
            return out
        for row in data:
            fs = str(row.get("symbol") or "").upper()
            orig = rev.get(fs) or rev.get(row.get("symbol") or "") or fs
            price = _finite(row.get("price"))
            if price is None or price == 0:
                continue
            chg = _finite(row.get("changesPercentage"))
            change = _finite(row.get("change"))
            if change is None and chg is not None:
                change = round(price * chg / 100.0, 6)
            out[orig] = {
                "symbol": orig,
                "status": "ok",
                "price": price,
                "change": change,
                "change_pct": chg,
                "volume": _finite(row.get("volume")),
                "provider": "fmp",
                "as_of": datetime.now(timezone.utc).isoformat(),
                "name": row.get("name"),
            }
            # also key by FMP symbol for movers lookup
            out[fs] = out[orig]
    except Exception as exc:
        from app.utils.secret_redact import redact_secrets

        logger.warning("FMP batch quote failed", error=redact_secrets(str(exc)))
    return out


async def enrich_change_map(symbols: list[str], *, timeout_s: float = 6.0) -> dict[str, dict[str, Any]]:
    """
    Merge yfinance batch (primary for %) + FMP (fill gaps) + Finnhub equity fill.

    Soft-fails on timeout so Terminal snapshot never hangs.
    """
    half = max(2.0, timeout_s * 0.45)
    try:
        yf_map, fmp_map = await asyncio.wait_for(
            asyncio.gather(
                batch_yf_enrich(symbols, timeout_s=half),
                batch_fmp_quotes(symbols, timeout_s=min(3.5, half)),
            ),
            timeout=max(3.0, timeout_s * 0.75),
        )
    except asyncio.TimeoutError:
        logger.warning("enrich_change_map timed out", n=len(symbols), timeout_s=timeout_s)
        yf_map, fmp_map = {}, {}
    merged: dict[str, dict[str, Any]] = {}
    for sym in symbols:
        y = yf_map.get(sym) or {}
        f = fmp_map.get(sym) or fmp_map.get(sym.lstrip("^")) or {}
        if not y and not f:
            continue
        row = {**f, **{k: v for k, v in y.items() if v is not None}}
        # Prefer yfinance batch % (prev close); FMP only fills gaps (never for ^VIX).
        if sym == "^VIX" and y.get("change_pct") is not None:
            row["change_pct"] = y["change_pct"]
            row["change"] = y.get("change")
        elif row.get("change_pct") is None and f.get("change_pct") is not None:
            row["change_pct"] = f["change_pct"]
            row["change"] = f.get("change")
        if row.get("price") is None and f.get("price") is not None:
            row["price"] = f["price"]
        row["status"] = "ok"
        merged[sym] = row

    missing = [
        s
        for s in symbols
        if s not in merged
        and not str(s).startswith("^")
        and "=" not in str(s)
        and not str(s).endswith(".ME")
    ]
    if missing and timeout_s > 1.5:
        try:
            from app.services.market_data.client import AlpacaClient
            from app.services.market_data.http_providers import key_configured
            from app.services.terminal_platform.market.index_fallbacks import fetch_keyed_equity_quote

            capped = missing[:24]
            filled: dict[str, dict[str, Any]] = {}

            if key_configured("alpaca"):
                alpaca = AlpacaClient()
                for i in range(0, len(capped), 40):
                    chunk = capped[i : i + 40]
                    try:
                        batch = await asyncio.wait_for(
                            alpaca.get_multiple_quotes(chunk),
                            timeout=min(3.5, timeout_s),
                        )
                    except Exception as exc:
                        logger.debug("alpaca batch fill failed", error=str(exc))
                        batch = {}
                    for sym, raw in (batch or {}).items():
                        price = _finite((raw or {}).get("price"))
                        if price is None:
                            continue
                        chg = _finite((raw or {}).get("change_pct"))
                        change = round(price * chg / 100.0, 6) if chg is not None else None
                        filled[sym.upper()] = {
                            "symbol": sym.upper(),
                            "status": "ok",
                            "price": price,
                            "change": change,
                            "change_pct": chg,
                            "provider": "alpaca",
                            "as_of": datetime.now(timezone.utc).isoformat(),
                        }

            still_missing = [s for s in capped if s.upper() not in filled]
            if still_missing:
                fills = await asyncio.wait_for(
                    asyncio.gather(
                        *[fetch_keyed_equity_quote(s, timeout_s=3.0) for s in still_missing[:8]],
                        return_exceptions=True,
                    ),
                    timeout=min(4.0, timeout_s),
                )
                for sym, row in zip(still_missing[:8], fills):
                    if isinstance(row, dict) and row.get("status") == "ok":
                        filled[sym.upper()] = row

            for sym, row in filled.items():
                merged[sym] = row
        except Exception as exc:
            logger.debug("enrich_change_map keyed fill failed", error=str(exc))
    return merged
