"""
HTTP adapter to the isolated regulatory sidecar.

This is the ONLY module in the main backend that knows the sidecar exists.
Client-facing responses never mention the upstream vendor.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

import httpx

from app.core.config import get_settings
from app.services.fundamental_data.models import FinraShortInterestRecord, RegulatoryDataResult, SecFiling
from app.services.fundamental_data.provider import FundamentalDataProvider

log = logging.getLogger(__name__)

_SERVICE_UNAVAILABLE = "Регуляторные данные временно недоступны"
_UPSTREAM_TIMEOUT = "Превышено время ожидания регуляторных данных"


def _normalize_sec_filing(raw: dict[str, Any]) -> SecFiling:
    return SecFiling(
        symbol=str(raw.get("symbol") or raw.get("ticker") or ""),
        form_type=str(raw.get("form_type") or raw.get("formType") or ""),
        filing_date=_as_str(raw.get("filing_date") or raw.get("filingDate")),
        accepted_date=_as_str(raw.get("accepted_date") or raw.get("acceptedDate")),
        link=_as_str(raw.get("link") or raw.get("url")),
        cik=_as_str(raw.get("cik")),
    )


def _normalize_finra_record(raw: dict[str, Any], symbol: str) -> FinraShortInterestRecord:
    return FinraShortInterestRecord(
        symbol=str(raw.get("symbol") or symbol),
        settlement_date=_as_str(raw.get("settlement_date") or raw.get("settlementDate")),
        current_short_position=_as_float(raw.get("current_short_position") or raw.get("currentShortPosition")),
        previous_short_position=_as_float(raw.get("previous_short_position") or raw.get("previousShortPosition")),
        days_to_cover=_as_float(raw.get("days_to_cover") or raw.get("daysToCover")),
        avg_daily_share_volume=_as_float(
            raw.get("avg_daily_share_volume") or raw.get("average_daily_share_volume")
        ),
    )


def _as_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class OpenBBFundamentalDataProvider(FundamentalDataProvider):
    """Calls the isolated sidecar over HTTP — never imports OpenBB directly."""

    def __init__(self, base_url: str, timeout_seconds: float = 8.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    @property
    def source_enabled(self) -> bool:
        return True

    async def get_sec_filings(
        self,
        ticker: str,
        *,
        limit: int = 20,
        form_type: Optional[str] = None,
    ) -> RegulatoryDataResult:
        start = time.perf_counter()
        symbol = ticker.strip().upper()
        params: dict[str, Any] = {"symbol": symbol, "limit": limit}
        if form_type:
            params["form_type"] = form_type.strip().upper()
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(f"{self._base_url}/v1/sec/filings", params=params)
            if resp.status_code == 503:
                return self._fail(start, _SERVICE_UNAVAILABLE, "SERVICE_UNAVAILABLE", symbol)
            if resp.status_code >= 400:
                return self._fail(start, _SERVICE_UNAVAILABLE, "UPSTREAM_ERROR", symbol)
            payload = resp.json()
            rows = [_normalize_sec_filing(row).model_dump() for row in payload.get("filings") or []]
            return RegulatoryDataResult(
                success=True,
                data={"symbol": symbol, "filings": rows, "count": len(rows)},
                source_enabled=True,
                duration_ms=(time.perf_counter() - start) * 1000,
                metadata={"ticker": symbol},
            )
        except httpx.TimeoutException:
            log.warning("regulatory sidecar timeout for SEC filings %s", symbol)
            return self._fail(start, _UPSTREAM_TIMEOUT, "TIMEOUT", symbol)
        except httpx.HTTPError as exc:
            log.warning("regulatory sidecar HTTP error for SEC filings %s: %s", symbol, exc)
            return self._fail(start, _SERVICE_UNAVAILABLE, "SERVICE_UNAVAILABLE", symbol)

    async def get_finra_short_interest(
        self,
        ticker: str,
        *,
        limit: int = 12,
    ) -> RegulatoryDataResult:
        start = time.perf_counter()
        symbol = ticker.strip().upper()
        params = {"symbol": symbol, "limit": limit}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(f"{self._base_url}/v1/finra/short-interest", params=params)
            if resp.status_code == 503:
                return self._fail(start, _SERVICE_UNAVAILABLE, "SERVICE_UNAVAILABLE", symbol)
            if resp.status_code >= 400:
                return self._fail(start, _SERVICE_UNAVAILABLE, "UPSTREAM_ERROR", symbol)
            payload = resp.json()
            rows = [
                _normalize_finra_record(row, symbol).model_dump()
                for row in payload.get("records") or []
            ]
            return RegulatoryDataResult(
                success=True,
                data={"symbol": symbol, "records": rows, "count": len(rows)},
                source_enabled=True,
                duration_ms=(time.perf_counter() - start) * 1000,
                metadata={"ticker": symbol},
            )
        except httpx.TimeoutException:
            log.warning("regulatory sidecar timeout for FINRA short interest %s", symbol)
            return self._fail(start, _UPSTREAM_TIMEOUT, "TIMEOUT", symbol)
        except httpx.HTTPError as exc:
            log.warning("regulatory sidecar HTTP error for FINRA short interest %s: %s", symbol, exc)
            return self._fail(start, _SERVICE_UNAVAILABLE, "SERVICE_UNAVAILABLE", symbol)

    def _fail(
        self,
        start: float,
        message: str,
        code: str,
        symbol: str,
    ) -> RegulatoryDataResult:
        return RegulatoryDataResult(
            success=False,
            error=message,
            error_code=code,
            source_enabled=True,
            duration_ms=(time.perf_counter() - start) * 1000,
            metadata={"ticker": symbol},
        )


def build_openbb_provider() -> OpenBBFundamentalDataProvider:
    settings = get_settings()
    return OpenBBFundamentalDataProvider(
        base_url=str(settings.OPENBB_SERVICE_URL),
        timeout_seconds=settings.OPENBB_SERVICE_TIMEOUT_SECONDS,
    )
