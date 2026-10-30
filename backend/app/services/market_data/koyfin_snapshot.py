"""FMP Key Metrics/Ratios snapshot, FMP stock screener, Twelve Data technicals."""
from __future__ import annotations

from typing import Any

import httpx

from app.core.config import get_settings
from app.core.http_proxy import httpx_client_kwargs
from app.core.logging import get_logger
from app.services.market_data.fmp_provider import (
    TIMEOUT,
    _first_row,
    _fmp_get,
    _is_fmp_candidate,
    fetch_fmp_fundamentals,
)
from app.services.market_data.http_providers import twelve_data_api_key

logger = get_logger(__name__)


def _num(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


async def fetch_fmp_fundamentals_snapshot(symbol: str) -> dict[str, Any]:
    """Key Metrics + Ratios + profile snapshot for a single-glance panel."""
    base = await fetch_fmp_fundamentals(symbol)
    if not base and not _is_fmp_candidate(symbol):
        return {"symbol": symbol.upper(), "source": None}

    settings = get_settings()
    if not settings.FMP_API_KEY.strip():
        return {**base, "symbol": symbol.upper()} if base else {"symbol": symbol.upper(), "source": None}

    sym = symbol.strip().upper()
    async with httpx.AsyncClient(**httpx_client_kwargs(foreign=True, timeout=TIMEOUT)) as client:
        ratios_raw = await _fmp_get(client, f"/ratios/{sym}", limit=1)
        metrics_ttm = await _fmp_get(client, f"/key-metrics-ttm/{sym}")
        ratios_ttm = await _fmp_get(client, f"/ratios-ttm/{sym}")

    ratios = _first_row(ratios_raw)
    metrics_t = _first_row(metrics_ttm)
    ratios_t = _first_row(ratios_ttm)

    extra = {
        "gross_margin": _num(ratios.get("grossProfitMargin") or ratios_t.get("grossProfitMarginTTM")),
        "operating_margin": _num(ratios.get("operatingProfitMargin") or ratios_t.get("operatingProfitMarginTTM")),
        "net_profit_margin": _num(ratios.get("netProfitMargin") or ratios_t.get("netProfitMarginTTM")),
        "price_to_sales": _num(ratios.get("priceToSalesRatio") or ratios_t.get("priceToSalesRatioTTM")),
        "peg": _num(metrics_t.get("pegRatioTTM") or ratios.get("pegRatio")),
        "ev_to_ebitda": _num(metrics_t.get("enterpriseValueOverEBITDATTM") or ratios.get("enterpriseValueMultiple")),
        "interest_coverage": _num(ratios.get("interestCoverage") or ratios_t.get("interestCoverageTTM")),
        "quick_ratio": _num(ratios.get("quickRatio") or ratios_t.get("quickRatioTTM")),
        "roic": _num(metrics_t.get("roicTTM") or ratios.get("returnOnCapitalEmployed")),
        "fcf_per_share": _num(metrics_t.get("freeCashFlowPerShareTTM") or ratios.get("freeCashFlowPerShare")),
        "payout_ratio": _num(ratios.get("dividendPayoutRatio") or ratios_t.get("dividendPayoutRatioTTM")),
        "ratios_source": "fmp_ratios" if ratios or ratios_t else None,
        "metrics_source": "fmp_key_metrics" if metrics_t else None,
    }
    out = {**base, **{k: v for k, v in extra.items() if v is not None}}
    out.setdefault("symbol", sym)
    return out


async def fetch_twelve_data_technicals(symbol: str) -> dict[str, Any]:
    """RSI / SMA from Twelve Data when keyed; otherwise empty (caller may fall back)."""
    api_key = twelve_data_api_key()
    if not api_key:
        return {}
    sym = symbol.strip().upper()
    timeout = httpx.Timeout(8.0, connect=4.0)
    out: dict[str, Any] = {"source": "twelvedata"}
    try:
        async with httpx.AsyncClient(**httpx_client_kwargs(foreign=True, timeout=timeout)) as client:
            rsi_resp = await client.get(
                "https://api.twelvedata.com/rsi",
                params={"symbol": sym, "interval": "1day", "time_period": 14, "apikey": api_key},
            )
            sma_resp = await client.get(
                "https://api.twelvedata.com/sma",
                params={"symbol": sym, "interval": "1day", "time_period": 20, "apikey": api_key},
            )
        rsi_json = rsi_resp.json() if rsi_resp.is_success else {}
        sma_json = sma_resp.json() if sma_resp.is_success else {}
        rsi_values = rsi_json.get("values") if isinstance(rsi_json, dict) else None
        sma_values = sma_json.get("values") if isinstance(sma_json, dict) else None
        if isinstance(rsi_values, list) and rsi_values:
            out["rsi"] = _num(rsi_values[0].get("rsi"))
        if isinstance(sma_values, list) and sma_values:
            out["sma20"] = _num(sma_values[0].get("sma"))
    except Exception as exc:
        logger.debug("Twelve Data technicals failed", symbol=sym, error=str(exc))
        return {}
    return {k: v for k, v in out.items() if v is not None}


async def _fmp_get_url(client: httpx.AsyncClient, url: str, **params: Any) -> Any:
    key = get_settings().FMP_API_KEY.strip()
    if not key:
        return None
    try:
        resp = await client.get(url, params={"apikey": key, **params})
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception:  # noqa: BLE001
        return None


async def fetch_fmp_screener(filters: dict[str, Any], limit: int = 50) -> list[dict[str, Any]]:
    """Proxy FMP /stock-screener with a bounded filter set."""
    settings = get_settings()
    if not settings.FMP_API_KEY.strip():
        return []

    allowed = {
        "marketCapMoreThan",
        "marketCapLowerThan",
        "priceMoreThan",
        "priceLowerThan",
        "betaMoreThan",
        "betaLowerThan",
        "volumeMoreThan",
        "volumeLowerThan",
        "peMoreThan",
        "peLowerThan",
        "sector",
        "industry",
        "exchange",
        "country",
        "isEtf",
        "isFund",
        "isActivelyTrading",
        "limit",
    }
    params: dict[str, Any] = {"limit": min(max(limit, 1), 100)}
    for key, value in filters.items():
        if key not in allowed or value is None or value == "":
            continue
        params[key] = value

    async with httpx.AsyncClient(**httpx_client_kwargs(foreign=True, timeout=TIMEOUT)) as client:
        # Keys issued after Aug 2025 only see /stable; older keys keep /api/v3.
        raw = await _fmp_get_url(client, "https://financialmodelingprep.com/stable/company-screener", **params)
        if not isinstance(raw, list) or not raw:
            raw = await _fmp_get(client, "/stock-screener", **params)
    if not isinstance(raw, list):
        return []

    rows: list[dict[str, Any]] = []
    for item in raw[: params["limit"]]:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").upper()
        if not symbol:
            continue
        rows.append(
            {
                "symbol": symbol,
                "name": item.get("companyName") or item.get("name"),
                "exchange": item.get("exchangeShortName") or item.get("exchange"),
                "sector": item.get("sector"),
                "industry": item.get("industry"),
                "price": _num(item.get("price")),
                "market_cap": _num(item.get("marketCap")),
                "beta": _num(item.get("beta")),
                "volume": _num(item.get("volume")),
                "pe": _num(item.get("pe") or item.get("priceEarningsRatio")),
                "dividend": (lambda d, p: (d / p) if d is not None and p else None)(
                    _num(item.get("lastAnnualDividend") or item.get("dividend")), _num(item.get("price"))
                ),  # yield, fraction
                "country": item.get("country"),
                "is_etf": item.get("isEtf"),
                "source": "fmp",
            }
        )
    return rows
