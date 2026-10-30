"""Financial Modeling Prep (FMP) fundamentals for US equities."""
from __future__ import annotations

from typing import Any

import httpx

from app.core.config import get_settings
from app.core.http_proxy import httpx_client_kwargs
from app.core.logging import get_logger

logger = get_logger(__name__)

FMP_BASE_URL = "https://financialmodelingprep.com/api/v3"
TIMEOUT = httpx.Timeout(15.0, connect=5.0)

# Crypto and non-equity symbols should skip FMP.
_FMP_SKIP_SUFFIXES = ("-USD", "-USDT", "-EUR", "-GBP")


def _is_fmp_candidate(symbol: str) -> bool:
    """True for plain US-style equity tickers."""
    sym = symbol.strip().upper()
    if not sym or any(sym.endswith(s) for s in _FMP_SKIP_SUFFIXES):
        return False
    if sym.startswith("^"):
        return False
    return sym.replace(".", "").isalnum()


def _first_row(payload: Any) -> dict[str, Any]:
    if isinstance(payload, list) and payload:
        row = payload[0]
        return row if isinstance(row, dict) else {}
    if isinstance(payload, dict):
        return payload
    return {}


def _normalize_fundamentals(
    profile: dict[str, Any],
    metrics: dict[str, Any],
    income: dict[str, Any],
) -> dict[str, Any]:
    market_cap = profile.get("mktCap") or metrics.get("marketCap")
    pe = (
        profile.get("pe")
        or metrics.get("peRatio")
        or metrics.get("priceEarningsRatio")
    )
    eps = profile.get("eps") or income.get("eps") or metrics.get("netIncomePerShare")
    dividend_yield = profile.get("dividendYield")
    if dividend_yield is None and profile.get("lastDiv") and profile.get("price"):
        try:
            dividend_yield = float(profile["lastDiv"]) / float(profile["price"])
        except (TypeError, ValueError, ZeroDivisionError):
            dividend_yield = None

    out: dict[str, Any] = {
        "symbol": profile.get("symbol"),
        "exchange": profile.get("exchangeShortName") or profile.get("exchange"),
        "currency": profile.get("currency") or "USD",
        "source": "fmp",
        "market_cap": market_cap,
        "pe_ratio": pe,
        "eps": eps,
        "dividend_yield": dividend_yield,
        "beta": profile.get("beta") or metrics.get("beta"),
        "roe": metrics.get("roe") or metrics.get("returnOnEquity"),
        "roa": metrics.get("roa") or metrics.get("returnOnAssets"),
        "sector": profile.get("sector"),
        "industry": profile.get("industry"),
        "revenue": income.get("revenue"),
        "net_income": income.get("netIncome"),
        "gross_profit": income.get("grossProfit"),
        "operating_income": income.get("operatingIncome"),
        "ebitda": income.get("ebitda"),
        "profit_margin": metrics.get("netProfitMargin"),
        "debt_to_equity": metrics.get("debtToEquity"),
        "current_ratio": metrics.get("currentRatio"),
        "price_to_book": metrics.get("pbRatio") or metrics.get("priceToBookRatio"),
        "enterprise_value": metrics.get("enterpriseValue"),
        "short_name": profile.get("companyName"),
    }
    range_low = profile.get("range")
    if isinstance(range_low, str) and "-" in range_low:
        parts = range_low.split("-", 1)
        try:
            out["week52_low"] = float(parts[0].strip())
            out["week52_high"] = float(parts[1].strip())
        except ValueError:
            pass
    return {k: v for k, v in out.items() if v is not None}


async def _fmp_get(client: httpx.AsyncClient, path: str, **params: Any) -> Any:
    settings = get_settings()
    api_key = settings.FMP_API_KEY.strip()
    if not api_key:
        return None
    query = {"apikey": api_key, **params}
    try:
        resp = await client.get(f"{FMP_BASE_URL}{path}", params=query)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.debug("FMP request failed", path=path, error=str(exc))
        return None


async def fetch_fmp_fundamentals(symbol: str) -> dict[str, Any]:
    """Load FMP profile, key metrics, and income statement for a US ticker."""
    if not _is_fmp_candidate(symbol):
        return {}

    settings = get_settings()
    if not settings.FMP_API_KEY.strip():
        return {}

    sym = symbol.strip().upper()
    async with httpx.AsyncClient(**httpx_client_kwargs(foreign=True, timeout=TIMEOUT)) as client:
        profile_raw, metrics_raw, income_raw = await _fmp_get(client, f"/profile/{sym}"), await _fmp_get(
            client, f"/key-metrics/{sym}", limit=1
        ), await _fmp_get(client, f"/income-statement/{sym}", limit=1)

    profile = _first_row(profile_raw)
    if not profile:
        return {}

    metrics = _first_row(metrics_raw)
    income = _first_row(income_raw)
    return _normalize_fundamentals(profile, metrics, income)
