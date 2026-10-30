"""Lightweight quote fallbacks when Yahoo/yfinance/FMP are blocked from the VPS."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from app.core.logging import get_logger
from app.services.terminal_platform.market.quote_cache import (
    finnhub_upstream_allowed,
    get_cached_keyed_quote,
    set_cached_keyed_quote,
)
from app.utils.secret_redact import redact_secrets

logger = get_logger(__name__)

# Yahoo/index/futures → liquid ETF (or equity) aliases for Finnhub/Alpaca/Polygon.
# Levels are ETF prices (not index points) except where noted; daily % is still useful.
INDEX_EQUITY_ALIASES: dict[str, str] = {
    "^GSPC": "SPY",
    "^IXIC": "QQQ",
    "^NDX": "QQQ",
    "^DJI": "DIA",
    "^RUT": "IWM",
    "^FTSE": "EWU",
    "^GDAXI": "EWG",
    "^FCHI": "EWQ",
    "^N225": "EWJ",
    "^HSI": "EWH",
    "000001.SS": "ASHR",
    "^KS11": "EWY",
    "GC=F": "GLD",
    "CL=F": "USO",
    "DX-Y.NYB": "UUP",
    "^TNX": "TLT",  # bond ETF — directionally inverse to yields; better than empty
    "^VIX": "VIXY",  # last-resort vol ETF when CBOE/Yahoo blocked (level ≈ rough only)
}

def equity_alias_for(api_symbol: str) -> Optional[str]:
    return INDEX_EQUITY_ALIASES.get((api_symbol or "").strip())


def _finite(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")) or f == 0.0:
        return None
    return f


async def fetch_cboe_vix(*, timeout_s: float = 4.0) -> Optional[dict[str, Any]]:
    """CBOE delayed ^VIX — works when Yahoo is geo-blocked from the VPS."""
    import httpx

    from app.core.http_proxy import httpx_client_kwargs

    url = "https://cdn.cboe.com/api/global/delayed_quotes/quotes/%5EVIX.json"
    try:
        async with httpx.AsyncClient(
            **httpx_client_kwargs(foreign=True, timeout=httpx.Timeout(timeout_s, connect=min(2.5, timeout_s)))
        ) as client:
            resp = await client.get(url)
            if resp.status_code >= 400:
                return None
            data = resp.json()
        quote = data.get("data") if isinstance(data, dict) else None
        if not isinstance(quote, dict):
            return None
        price = _finite(quote.get("current_price") or quote.get("price") or quote.get("last"))
        if price is None:
            return None
        prev = _finite(quote.get("prev_close") or quote.get("previous_close") or quote.get("close"))
        chg = None
        if prev and prev > 0:
            chg = round((price / prev - 1.0) * 100.0, 4)
        change = _finite(quote.get("price_change") or quote.get("change"))
        if change is None and chg is not None:
            change = round(price * chg / 100.0, 6)
        return {
            "symbol": "^VIX",
            "status": "ok",
            "price": price,
            "change": change,
            "change_pct": chg,
            "provider": "cboe",
            "as_of": datetime.now(timezone.utc).isoformat(),
            "reason": None,
        }
    except Exception as exc:
        logger.warning("CBOE VIX fetch failed", error=redact_secrets(str(exc)))
        return None


async def fetch_keyed_equity_quote(
    symbol: str,
    *,
    preferred: Optional[str] = None,
    timeout_s: float = 4.0,
) -> Optional[dict[str, Any]]:
    """Finnhub → Alpaca → Polygon for plain equity/ETF tickers (not Yahoo indices)."""
    from app.services.market_data.client import AlpacaClient, PolygonClient
    from app.services.market_data.http_providers import FinnhubMarketClient, key_configured

    sym = (symbol or "").strip().upper()
    if not sym or sym.startswith("^") or "=" in sym:
        return None

    order = ["alpaca", "polygon", "finnhub"]
    if preferred and preferred in order:
        order = [preferred] + [p for p in order if p != preferred]

    async def _one(name: str) -> Optional[dict[str, Any]]:
        if not key_configured(name):
            return None

        cached = await get_cached_keyed_quote(name, sym)
        if cached:
            return cached

        if name == "finnhub" and not await finnhub_upstream_allowed():
            return None

        try:
            if name == "finnhub":
                raw = await FinnhubMarketClient().get_latest_quote(sym)
            elif name == "alpaca":
                raw = await AlpacaClient().get_latest_quote(sym)
            else:
                raw = await PolygonClient().get_latest_quote(sym)
        except Exception as exc:
            logger.debug("keyed equity quote failed", provider=name, symbol=sym, error=redact_secrets(str(exc)))
            return None
        price = _finite((raw or {}).get("price"))
        if price is None:
            return None
        chg = _finite((raw or {}).get("change_pct"))
        change = None
        if chg is not None:
            change = round(price * chg / 100.0, 6)
        result = {
            "symbol": sym,
            "status": "ok",
            "price": price,
            "change": change,
            "change_pct": chg,
            "provider": name,
            "as_of": (raw or {}).get("timestamp") or datetime.now(timezone.utc).isoformat(),
            "volume": _finite((raw or {}).get("volume")),
            "reason": None,
        }
        await set_cached_keyed_quote(name, sym, result)
        return result

    for name in order:
        result = await _one(name)
        if result:
            return result
    return None


async def fetch_fred_us10y(*, timeout_s: float = 4.0) -> Optional[dict[str, Any]]:
    """FRED DGS10 — actual US 10Y constant-maturity yield when FRED_API_KEY is set."""
    from app.core.config import settings

    api_key = (settings.FRED_API_KEY or "").strip()
    if not api_key:
        return None
    import httpx

    from app.core.http_proxy import httpx_client_kwargs

    try:
        async with httpx.AsyncClient(
            **httpx_client_kwargs(foreign=True, timeout=httpx.Timeout(timeout_s, connect=min(2.5, timeout_s)))
        ) as client:
            resp = await client.get(
                "https://api.stlouisfed.org/fred/series/observations",
                params={
                    "series_id": "DGS10",
                    "api_key": api_key,
                    "file_type": "json",
                    "sort_order": "desc",
                    "limit": 5,
                },
            )
            if resp.status_code >= 400:
                return None
            data = resp.json()
        rows = data.get("observations") if isinstance(data, dict) else None
        if not isinstance(rows, list) or not rows:
            return None
        vals: list[tuple[str, float]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            raw = row.get("value")
            if raw in (None, "."):
                continue
            v = _finite(raw)
            if v is None:
                continue
            vals.append((str(row.get("date") or ""), v))
            if len(vals) >= 2:
                break
        if not vals:
            return None
        price = vals[0][1]
        chg = None
        if len(vals) >= 2 and vals[1][1]:
            chg = round((price - vals[1][1]), 4)  # yield change in percentage points
        return {
            "symbol": "^TNX",
            "status": "ok",
            "price": price,
            "change": chg,
            "change_pct": None,
            "provider": "fred:DGS10",
            "as_of": datetime.now(timezone.utc).isoformat(),
            "reason": None,
        }
    except Exception as exc:
        logger.warning("FRED US10Y fetch failed", error=redact_secrets(str(exc)))
        return None


async def fetch_index_quote_with_fallbacks(
    api_symbol: str,
    *,
    preferred_provider: Optional[str] = None,
    chain_budget_s: float = 5.0,
    try_native: bool = True,
) -> dict[str, Any]:
    """
    Quote path for Terminal indices / global snapshot.

    Order:
      1) CBOE for ^VIX
      2) ProviderRouter (native symbol) — optional, often times out on RU VPS
      3) Keyed equity alias (SPY/QQQ/GLD/…) when Yahoo/FMP are blocked
    """
    api = (api_symbol or "").strip()
    if not api:
        return {"symbol": api_symbol, "status": "no_data", "reason": "empty_symbol"}

    if api.upper() in {"^VIX", "VIX"}:
        cboe = await fetch_cboe_vix(timeout_s=min(4.0, max(2.0, chain_budget_s)))
        if cboe:
            return cboe
        # Skip Yahoo native for VIX — burns chain budget via proxy 502/timeouts on RU VPS.
        alias = equity_alias_for("^VIX") or "VIXY"
        proxied = await fetch_keyed_equity_quote(alias, timeout_s=min(4.0, max(2.0, chain_budget_s)))
        if proxied:
            return {
                "symbol": "^VIX",
                "status": "ok",
                "price": proxied.get("price"),
                "change": proxied.get("change"),
                "change_pct": proxied.get("change_pct"),
                "provider": f"{proxied.get('provider')}:{alias}",
                "as_of": proxied.get("as_of"),
                "reason": f"vol_etf_proxy:{alias}",
            }
        return {"symbol": "^VIX", "status": "no_data", "reason": "vix_providers_unavailable"}

    if api.upper() in {"^TNX", "TNX", "US10Y"}:
        fred = await fetch_fred_us10y(timeout_s=min(4.0, max(2.0, chain_budget_s)))
        if fred:
            return fred

    native: dict[str, Any] = {"symbol": api, "status": "no_data", "reason": "native_skipped"}
    if try_native and preferred_provider in {"moex_iss", "binance_public"}:
        from app.services.terminal_platform.market.quotes import fetch_quote_safe

        native = await fetch_quote_safe(
            api,
            preferred_provider=preferred_provider,
            backfill_change=False,
            chain_budget_s=min(chain_budget_s, 3.5),
        )
        if native.get("status") == "ok" and _finite(native.get("price")) is not None:
            return native

    alias = equity_alias_for(api)
    # Crypto / MOEX natives already handled above; plain BTC-USD falls through to binance via router.
    if api.upper() in {"BTC-USD", "BTCUSDT", "BTC/USDT"}:
        from app.services.terminal_platform.market.quotes import fetch_quote_safe

        crypto = await fetch_quote_safe(
            "BTC-USD",
            preferred_provider="binance_public",
            backfill_change=False,
            chain_budget_s=min(chain_budget_s, 3.0),
        )
        if crypto.get("status") == "ok":
            return crypto

    if not alias:
        if try_native and preferred_provider not in {"moex_iss", "binance_public"}:
            from app.services.terminal_platform.market.quotes import fetch_quote_safe

            native = await fetch_quote_safe(
                api,
                preferred_provider=preferred_provider or "yfinance",
                backfill_change=False,
                chain_budget_s=min(2.5, chain_budget_s),
            )
            if native.get("status") == "ok" and _finite(native.get("price")) is not None:
                return native
        return native if native else {"symbol": api, "status": "no_data", "reason": "no_data"}

    proxied = await fetch_keyed_equity_quote(alias, timeout_s=min(4.0, max(2.0, chain_budget_s)))
    if not proxied:
        return {
            "symbol": api,
            "status": "no_data",
            "reason": native.get("reason") or f"alias_{alias}_failed",
            "provider": native.get("provider"),
        }

    return {
        "symbol": api,
        "status": "ok",
        "price": proxied.get("price"),
        "change": proxied.get("change"),
        "change_pct": proxied.get("change_pct"),
        "provider": f"{proxied.get('provider')}:{alias}",
        "as_of": proxied.get("as_of"),
        "volume": proxied.get("volume"),
        "reason": f"etf_proxy:{alias}",
    }
