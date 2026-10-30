"""
Macro indicator ingestion from official public APIs (FRED, CBR RF).

Ingestion only — no analysis logic. Series mapping:
  rate_cb      — CBR KeyRate (RU), FRED FEDFUNDS (US proxy)
  cpi          — FRED CPIAUCSL
  unemployment — FRED UNRATE
  dxy          — FRED DTWEXBGS
  vix          — FRED VIXCLS
  oil_brent    — FRED DCOILBRENTEU
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.domain.market_data import MacroIndicatorORM

logger = get_logger(__name__)

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
CBR_KEY_RATE_URL = "https://www.cbr.ru/DailyInfoWebServ/DailyInfo.asmx"

FRED_SERIES: dict[str, str] = {
    "cpi": "CPIAUCSL",
    "unemployment": "UNRATE",
    "dxy": "DTWEXBGS",
    "vix": "VIXCLS",
    "oil_brent": "DCOILBRENTEU",
    "rate_cb_us": "FEDFUNDS",
}

CBR_SOAP_TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xmlns:xsd="http://www.w3.org/2001/XMLSchema"
               xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <KeyRateXML xmlns="http://web.cbr.ru/">
      <fromDate>{from_date}</fromDate>
      <ToDate>{to_date}</ToDate>
    </KeyRateXML>
  </soap:Body>
</soap:Envelope>"""


def compute_spread_bps(
    bid_depth: list[dict[str, str | float]],
    ask_depth: list[dict[str, str | float]],
) -> float | None:
    """Best bid/ask spread in basis points relative to mid price."""
    if not bid_depth or not ask_depth:
        return None
    try:
        best_bid = float(bid_depth[0]["price"])
        best_ask = float(ask_depth[0]["price"])
    except (KeyError, TypeError, ValueError):
        return None
    if best_bid <= 0 or best_ask <= 0 or best_ask <= best_bid:
        return None
    mid = (best_bid + best_ask) / 2.0
    return round((best_ask - best_bid) / mid * 10_000, 4)


def normalize_depth_levels(raw_levels: list[list[str]]) -> list[dict[str, str]]:
    """Convert Binance [price, qty] pairs to jsonb-friendly dicts."""
    levels: list[dict[str, str]] = []
    for level in raw_levels or []:
        if len(level) < 2:
            continue
        levels.append({"price": str(level[0]), "qty": str(level[1])})
    return levels


def parse_cbr_key_rate_xml(xml_text: str) -> list[dict[str, Any]]:
    """Parse CBR KeyRateXML SOAP response into indicator rows."""
    rows: list[dict[str, Any]] = []
    for match in re.finditer(r"<KR><DT>(.*?)</DT><Rate>(.*?)</Rate></KR>", xml_text):
        dt_raw, rate_raw = match.group(1), match.group(2)
        try:
            published_at = datetime.fromisoformat(dt_raw.replace("Z", "+00:00"))
            if published_at.tzinfo is None:
                published_at = published_at.replace(tzinfo=timezone.utc)
            value = Decimal(rate_raw.strip())
        except (ValueError, InvalidOperation):
            continue
        rows.append(
            {
                "indicator_code": "rate_cb",
                "value": value,
                "published_at": published_at,
                "source": "cbr_rf",
            }
        )
    if not rows:
        try:
            root = ET.fromstring(xml_text)
            for kr in root.iter():
                if kr.tag.endswith("KR"):
                    dt_el = next((c for c in kr if c.tag.endswith("DT")), None)
                    rate_el = next((c for c in kr if c.tag.endswith("Rate")), None)
                    if dt_el is None or rate_el is None or not rate_el.text:
                        continue
                    published_at = datetime.fromisoformat(dt_el.text.replace("Z", "+00:00"))
                    if published_at.tzinfo is None:
                        published_at = published_at.replace(tzinfo=timezone.utc)
                    rows.append(
                        {
                            "indicator_code": "rate_cb",
                            "value": Decimal(rate_el.text.strip()),
                            "published_at": published_at,
                            "source": "cbr_rf",
                        }
                    )
        except ET.ParseError:
            pass
    return rows


def parse_fred_observations(
    indicator_code: str,
    payload: dict[str, Any],
    *,
    source: str = "fred",
) -> list[dict[str, Any]]:
    """Map FRED observations JSON to macro_indicators rows."""
    rows: list[dict[str, Any]] = []
    for obs in payload.get("observations", []):
        raw_date = obs.get("date")
        raw_value = obs.get("value")
        if not raw_date or raw_value in (None, ".", ""):
            continue
        try:
            published_at = datetime.strptime(raw_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            value = Decimal(str(raw_value))
        except (ValueError, InvalidOperation):
            continue
        rows.append(
            {
                "indicator_code": indicator_code,
                "value": value,
                "published_at": published_at,
                "source": source,
            }
        )
    return rows


async def fetch_cbr_key_rate(
    client: httpx.AsyncClient,
    *,
    lookback_days: int = 365,
) -> list[dict[str, Any]]:
    """Fetch Russian CB key rate via official DailyInfo SOAP web service."""
    now = datetime.now(timezone.utc)
    from_date = (now - timedelta(days=lookback_days)).strftime("%Y-%m-%dT00:00:00")
    to_date = now.strftime("%Y-%m-%dT00:00:00")
    body = CBR_SOAP_TEMPLATE.format(from_date=from_date, to_date=to_date)
    response = await client.post(
        CBR_KEY_RATE_URL,
        content=body.encode("utf-8"),
        headers={
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": '"http://web.cbr.ru/KeyRateXML"',
        },
        timeout=30.0,
    )
    response.raise_for_status()
    return parse_cbr_key_rate_xml(response.text)


async def fetch_fred_series(
    client: httpx.AsyncClient,
    indicator_code: str,
    series_id: str,
    *,
    lookback_days: int = 365,
) -> list[dict[str, Any]]:
    """Fetch one FRED series (requires FRED_API_KEY)."""
    if not settings.FRED_API_KEY:
        logger.info("FRED_API_KEY not configured, skipping series", series=series_id)
        return []

    start = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    params = {
        "series_id": series_id,
        "api_key": settings.FRED_API_KEY,
        "file_type": "json",
        "observation_start": start,
        "sort_order": "asc",
    }
    response = await client.get(FRED_BASE, params=params, timeout=30.0)
    response.raise_for_status()
    return parse_fred_observations(indicator_code, response.json())


async def fetch_all_macro_indicators(*, lookback_days: int = 365) -> list[dict[str, Any]]:
    """Pull all configured macro indicators from public APIs."""
    rows: list[dict[str, Any]] = []
    async with httpx.AsyncClient() as client:
        try:
            rows.extend(await fetch_cbr_key_rate(client, lookback_days=lookback_days))
        except Exception as exc:
            logger.warning("CBR key rate fetch failed", error=str(exc))

        for indicator_code, series_id in FRED_SERIES.items():
            try:
                mapped_code = "rate_cb" if indicator_code == "rate_cb_us" else indicator_code
                rows.extend(
                    await fetch_fred_series(
                        client,
                        mapped_code,
                        series_id,
                        lookback_days=lookback_days,
                    )
                )
            except Exception as exc:
                logger.warning(
                    "FRED series fetch failed",
                    indicator=indicator_code,
                    series=series_id,
                    error=str(exc),
                )
    return rows


async def store_macro_indicators(session: AsyncSession, rows: list[dict[str, Any]]) -> int:
    """Upsert macro indicator rows; returns number of attempted inserts."""
    if not rows:
        return 0

    stored = 0
    for row in rows:
        stmt = (
            insert(MacroIndicatorORM)
            .values(**row)
            .on_conflict_do_nothing(constraint="macro_indicators_indicator_code_published_at_source_key")
        )
        result = await session.execute(stmt)
        stored += result.rowcount or 0

    await session.commit()
    return stored


async def fetch_and_store_macro_indicators(
    session: AsyncSession,
    *,
    lookback_days: int = 365,
) -> dict[str, Any]:
    """Fetch from APIs and persist to macro_indicators table."""
    rows = await fetch_all_macro_indicators(lookback_days=lookback_days)
    stored = await store_macro_indicators(session, rows)
    return {"fetched": len(rows), "stored": stored}
