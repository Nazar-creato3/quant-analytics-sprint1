"""Live Bybit spot instrument list for tokenized equity capability checks."""
from __future__ import annotations

import time
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.services.execution.symbol_mapping import normalize_ui_symbol
from app.utils.cache import cache_get, cache_set

logger = get_logger(__name__)

BYBIT_INSTRUMENTS_CACHE_KEY = "execution:bybit:spot:tokenized:v2"
BYBIT_INSTRUMENTS_TTL_SECONDS = 900  # 15 minutes

# UI ticker aliases where execution symbol differs from naive {TICKER}XUSDT guess.
_BYBIT_UI_ALIASES: dict[str, str] = {
    "GOOG": "GOOGL",
}

_memory_cache: tuple[float, dict[str, str]] | None = None


def bybit_tokenized_candidate_symbol(ui_base: str) -> str:
    """Best-effort Bybit spot symbol for a US equity UI ticker."""
    base = normalize_ui_symbol(ui_base)
    alias_base = _BYBIT_UI_ALIASES.get(base, base)
    return f"{alias_base}XUSDT"


def _parse_tokenized_map(payload: dict[str, Any]) -> dict[str, str]:
    rows = (payload.get("result") or {}).get("list") or []
    out: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").upper()
        status = str(row.get("status") or "").upper()
        if status != "TRADING" or not symbol.endswith("XUSDT"):
            continue
        base = symbol[: -len("XUSDT")]
        if not base or not base.isalpha():
            continue
        out[base] = symbol
    for alias, canonical in _BYBIT_UI_ALIASES.items():
        exec_symbol = out.get(canonical)
        if exec_symbol:
            out[alias] = exec_symbol
    return out


async def _fetch_bybit_spot_tokenized_map(base_url: str | None = None) -> dict[str, str]:
    root = (base_url or getattr(settings, "BYBIT_API_BASE_URL", None) or "https://api.bybit.com").rstrip("/")
    url = f"{root}/v5/market/instruments-info"
    merged: dict[str, str] = {}
    cursor: str | None = None
    timeout = httpx.Timeout(20.0, connect=5.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        for _ in range(20):
            params: dict[str, str] = {"category": "spot", "limit": "1000"}
            if cursor:
                params["cursor"] = cursor
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            payload = resp.json()
            if int(payload.get("retCode", -1)) != 0:
                raise RuntimeError(payload.get("retMsg") or "Bybit instruments-info failed")
            merged.update(_parse_tokenized_map(payload))
            cursor = (payload.get("result") or {}).get("nextPageCursor") or None
            if not cursor:
                break

    logger.info("Bybit tokenized instrument cache refreshed", count=len(merged))
    return merged


async def get_bybit_tokenized_instruments(*, force_refresh: bool = False) -> dict[str, str]:
    """Return cached map of UI base ticker -> Bybit spot symbol (live API, TTL refresh)."""
    global _memory_cache

    if not force_refresh:
        cached = await cache_get(BYBIT_INSTRUMENTS_CACHE_KEY)
        if isinstance(cached, dict) and cached:
            return {str(k).upper(): str(v).upper() for k, v in cached.items()}
        if _memory_cache and (time.time() - _memory_cache[0]) < BYBIT_INSTRUMENTS_TTL_SECONDS:
            return dict(_memory_cache[1])

    try:
        fresh = await _fetch_bybit_spot_tokenized_map()
        _memory_cache = (time.time(), dict(fresh))
        await cache_set(BYBIT_INSTRUMENTS_CACHE_KEY, fresh, ttl=BYBIT_INSTRUMENTS_TTL_SECONDS)
        return fresh
    except Exception as exc:
        logger.warning("Bybit instrument refresh failed", error=str(exc))
        if _memory_cache:
            return dict(_memory_cache[1])
        cached = await cache_get(BYBIT_INSTRUMENTS_CACHE_KEY)
        if isinstance(cached, dict) and cached:
            return {str(k).upper(): str(v).upper() for k, v in cached.items()}
        return {}


async def bybit_supports_ui_ticker(ticker: str) -> bool:
    base = normalize_ui_symbol(ticker)
    instruments = await get_bybit_tokenized_instruments()
    if base in instruments:
        return True
    alias = _BYBIT_UI_ALIASES.get(base)
    return bool(alias and alias in instruments)


async def bybit_execution_symbol_for(ticker: str) -> str | None:
    base = normalize_ui_symbol(ticker)
    instruments = await get_bybit_tokenized_instruments()
    if base in instruments:
        return instruments[base]
    alias = _BYBIT_UI_ALIASES.get(base)
    if alias and alias in instruments:
        return instruments[alias]
    return None
