"""OilPriceAPI, API Ninjas and Riksbank SWEA clients for the macro registry.

Documented public endpoints only:
- OilPriceAPI: https://api.oilpriceapi.com/v1/prices/past_month?by_code=CODE (Authorization: Token KEY)
- API Ninjas:  https://api.api-ninjas.com/v1/commodityprice?name=NAME (X-Api-Key: KEY)
- Riksbank:    https://api.riksbank.se/swea/v1/Observations/{series}/{from} (key optional)
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.core.config import settings

OILPRICEAPI_BASE = "https://api.oilpriceapi.com/v1"
API_NINJAS_BASE = "https://api.api-ninjas.com/v1"
RIKSBANK_SWEA_BASE = "https://api.riksbank.se/swea/v1"


class SourceKeyMissing(RuntimeError):
    """The source needs a key that is not configured; the registry uses the fallback."""


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = datetime.strptime(text[:10], "%Y-%m-%d")
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ── OilPriceAPI ────────────────────────────────────────────────────────────
async def fetch_oilpriceapi(client: httpx.AsyncClient, code: str) -> str:
    key = (settings.OILPRICEAPI_API_KEY or "").strip()
    if not key:
        raise SourceKeyMissing("OILPRICEAPI_API_KEY is not configured")
    resp = await client.get(
        f"{OILPRICEAPI_BASE}/prices/past_month",
        params={"by_code": code},
        headers={"Authorization": f"Token {key}", "Accept": "application/json"},
        timeout=20.0,
    )
    resp.raise_for_status()
    return resp.text


def parse_oilpriceapi(payload: str | dict) -> list[dict[str, Any]]:
    """Rows {published_at, value}; accepts past_* (list) and latest (single) shapes."""
    data = json.loads(payload) if isinstance(payload, str) else payload
    body = data.get("data") if isinstance(data, dict) else None
    if isinstance(body, dict) and isinstance(body.get("prices"), list):
        items = body["prices"]
    elif isinstance(body, list):
        items = body
    elif isinstance(body, dict):
        items = [body]
    else:
        items = []
    by_day: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict) or item.get("price") is None:
            continue
        ts = _parse_ts(item.get("created_at") or item.get("timestamp"))
        if ts is None:
            continue
        day = ts.strftime("%Y-%m-%d")
        prev = by_day.get(day)
        if prev is None or ts > prev["published_at"]:
            by_day[day] = {"published_at": ts, "value": float(item["price"])}
    return [by_day[d] for d in sorted(by_day)]


# ── API Ninjas ─────────────────────────────────────────────────────────────
async def fetch_api_ninjas_commodity(client: httpx.AsyncClient, name: str) -> str:
    key = (settings.API_NINJAS_API_KEY or "").strip()
    if not key:
        raise SourceKeyMissing("API_NINJAS_API_KEY is not configured")
    resp = await client.get(
        f"{API_NINJAS_BASE}/commodityprice",
        params={"name": name},
        headers={"X-Api-Key": key, "Accept": "application/json"},
        timeout=20.0,
    )
    resp.raise_for_status()
    return resp.text


def parse_api_ninjas_commodity(payload: str | dict) -> list[dict[str, Any]]:
    data = json.loads(payload) if isinstance(payload, str) else payload
    rows = data if isinstance(data, list) else [data]
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("price") is None:
            continue
        ts = _parse_ts(row.get("updated")) or datetime.now(timezone.utc)
        out.append({"published_at": ts, "value": float(row["price"]), "exchange": row.get("exchange")})
    return out


# ── Riksbank SWEA ──────────────────────────────────────────────────────────
async def fetch_riksbank_series(client: httpx.AsyncClient, series_id: str, *, lookback_days: int = 365) -> str:
    start = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    headers = {"Accept": "application/json"}
    key = (settings.RIKSBANK_API_KEY or "").strip()
    if key:
        headers["Ocp-Apim-Subscription-Key"] = key
    resp = await client.get(f"{RIKSBANK_SWEA_BASE}/Observations/{series_id}/{start}", headers=headers, timeout=20.0)
    resp.raise_for_status()
    return resp.text


def parse_riksbank_observations(payload: str | list) -> list[dict[str, Any]]:
    data = json.loads(payload) if isinstance(payload, str) else payload
    rows = data if isinstance(data, list) else [data]
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("value") is None:
            continue
        ts = _parse_ts(row.get("date"))
        if ts is None:
            continue
        out.append({"published_at": ts, "value": float(row["value"])})
    out.sort(key=lambda r: r["published_at"])
    return out
