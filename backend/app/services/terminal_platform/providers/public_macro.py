"""Public EU/US macro: ECB, OECD SDMX, Eurostat JSON-stat, EIA v2 — no paid vendor."""
from __future__ import annotations

import time
from datetime import date, datetime
from typing import Any, Optional

import httpx

from app.core.config import settings
from app.core.http_proxy import httpx_client_kwargs
from app.services.terminal_platform.base import DataProvider, DataProviderConfig
from app.services.terminal_platform.models import FetchResult, MacroSeries
from app.services.terminal_platform.types import DataType, RateLimitConfig, Timeframe

ECB_ALIASES: dict[str, tuple[str, str]] = {
    "EURUSD": ("EXR", "D.USD.EUR.SP00.A"),
    "ECB_EURUSD": ("EXR", "D.USD.EUR.SP00.A"),
    "ECB_HICP": ("ICP", "M.U2.N.000000.4.ANR"),
    "EU_HICP": ("ICP", "M.U2.N.000000.4.ANR"),
}

OECD_ALIASES: dict[str, str] = {
    "OECD_CLI_USA": "OECD.SDD.STES,DSD_STES@DF_CLI/USA.M.LI...AA...H",
    "OECD_CLI": "OECD.SDD.STES,DSD_STES@DF_CLI/USA.M.LI...AA...H",
}

EUROSTAT_ALIASES: dict[str, tuple[str, dict[str, str]]] = {
    "EU_HICP_YOY": ("prc_hicp_manr", {"geo": "EA", "coicop": "CP00", "unit": "RCH_A"}),
    "EU_UNEMPLOYMENT": ("une_rt_m", {"geo": "EA", "age": "TOTAL", "sex": "T", "s_adj": "SA", "unit": "PC_ACT"}),
    "EU_GDP_GROWTH": ("tec00115", {"geo": "EA", "na_item": "B1GQ", "unit": "CLV_PCH_PRE"}),
    "EU_ESI_CONSUMER": ("ei_bsco_m", {"geo": "EA", "indic": "BS-CSMCI", "s_adj": "SA"}),
    "EU_ESI_INDUSTRY": ("ei_bsin_m", {"geo": "EA", "indic": "BS-ICI", "s_adj": "SA"}),
}

EIA_ALIASES: dict[str, str] = {
    "BRENT": "PET.RBRTE.D",
    "WTI": "PET.RWTC.D",
    "WTI_OIL": "PET.RWTC.D",
    "NG_HENRY_HUB": "NG.RNGWHHD.D",
    "EIA_BRENT": "PET.RBRTE.D",
}


def _sdmx_observations(payload: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        datasets = payload.get("dataSets") or []
        structure = payload.get("structure") or payload.get("meta") or {}
        dims = ((structure.get("dimensions") or {}).get("observation") or []) if isinstance(structure, dict) else []
        time_dim = next((d for d in dims if str(d.get("id") or "").lower() in {"time", "time_period"}), None)
        values: list[dict[str, Any]] = []
        for ds in datasets:
            series = ds.get("series") or {}
            if not series and "observations" in ds:
                series = {"": ds}
            for series_obj in series.values():
                obs = series_obj.get("observations") or {}
                for idx, row in obs.items():
                    val = row[0] if isinstance(row, list) and row else row
                    if val in (None, ".", ""):
                        continue
                    label = str(idx)
                    if time_dim:
                        cats = (time_dim.get("values") or [])
                        try:
                            label = str(cats[int(idx)].get("id") or cats[int(idx)].get("name") or idx)
                        except (ValueError, IndexError, TypeError, AttributeError):
                            label = str(idx)
                    values.append({"date": label, "value": float(val)})
        values.sort(key=lambda x: str(x["date"]))
        return values
    except (TypeError, ValueError, KeyError):
        return []


def _jsonstat_time_values(payload: dict[str, Any]) -> list[dict[str, Any]]:
    value = payload.get("value")
    if not isinstance(value, dict):
        return []
    dims = payload.get("dimension") or {}
    time_id = None
    for key, dim in dims.items():
        if str(key).lower() in {"time", "time_period"} or str((dim or {}).get("label") or "").lower() in {"time", "period"}:
            time_id = key
            break
    if time_id is None:
        return []
    index = ((dims.get(time_id) or {}).get("category") or {}).get("index") or {}
    inv = {int(v): k for k, v in index.items()} if index else {}
    out: list[dict[str, Any]] = []
    for k, v in value.items():
        if v is None:
            continue
        try:
            pos = int(k)
            label = inv.get(pos, str(k))
            out.append({"date": str(label), "value": float(v)})
        except (TypeError, ValueError):
            continue
    out.sort(key=lambda x: str(x["date"]))
    return out


class _MacroStubMixin:
    async def fetch_ohlcv(self, symbol: str, timeframe: Timeframe, from_date: datetime, to_date: datetime, **kwargs: Any) -> FetchResult:
        return self._unsupported(time.perf_counter(), "ohlcv")

    async def fetch_quote(self, symbol: str, **kwargs: Any) -> FetchResult:
        return self._unsupported(time.perf_counter(), "quote")

    async def fetch_fundamentals(self, symbol: str, **kwargs: Any) -> FetchResult:
        return self._unsupported(time.perf_counter(), "fundamentals")

    async def fetch_news(
        self,
        symbols: Optional[list[str]] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        limit: int = 50,
        **kwargs: Any,
    ) -> FetchResult:
        return self._unsupported(time.perf_counter(), "news")


class EcbDataProvider(_MacroStubMixin, DataProvider):
    def __init__(self, config: Optional[DataProviderConfig] = None):
        super().__init__(
            config
            or DataProviderConfig(
                name="ecb",
                base_url="https://data-api.ecb.europa.eu/service/data",
                rate_limit=RateLimitConfig(requests_per_minute=30, burst_size=5),
                priority=70,
                timeout_seconds=6.0,
            )
        )

    @property
    def supported_data_types(self) -> list[DataType]:
        return [DataType.MACRO_SERIES]

    async def fetch_macro_series(
        self,
        series_id: str,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        **kwargs: Any,
    ) -> FetchResult:
        start = time.perf_counter()
        self._record_request()
        flow, key = ECB_ALIASES.get(series_id.upper(), ("EXR", series_id))
        url = f"{self.config.base_url}/{flow}/{key}"
        try:
            kwargs_http = httpx_client_kwargs(foreign=True, timeout=httpx.Timeout(8.0, connect=4.0))
            async with httpx.AsyncClient(**kwargs_http) as client:
                resp = await client.get(url, params={"format": "jsondata"})
                resp.raise_for_status()
                payload = resp.json()
            values = _sdmx_observations(payload)
            if not values:
                return self._timed_failure(start=start, error="Empty ECB series", error_code="EMPTY")
            series = MacroSeries(
                series_id=f"{flow}.{key}",
                name=series_id,
                description=f"ECB Data Portal {flow}/{key}",
                country="EA",
                unit="varies",
                frequency="varies",
                values=values,
                provider=self.name,
                source_url=url,
            )
            return FetchResult(success=True, data=series, provider=self.name, duration_ms=(time.perf_counter() - start) * 1000)
        except Exception as exc:
            return self._failure_from_exc(start, exc)


class OecdDataProvider(_MacroStubMixin, DataProvider):
    def __init__(self, config: Optional[DataProviderConfig] = None):
        super().__init__(
            config
            or DataProviderConfig(
                name="oecd",
                base_url="https://sdmx.oecd.org/public/rest/data",
                rate_limit=RateLimitConfig(requests_per_minute=20, burst_size=4),
                priority=68,
                timeout_seconds=8.0,
            )
        )

    @property
    def supported_data_types(self) -> list[DataType]:
        return [DataType.MACRO_SERIES]

    async def fetch_macro_series(
        self,
        series_id: str,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        **kwargs: Any,
    ) -> FetchResult:
        start = time.perf_counter()
        self._record_request()
        path = OECD_ALIASES.get(series_id.upper(), series_id)
        url = f"{self.config.base_url}/{path}"
        params: dict[str, str] = {"format": "jsondata", "dimensionAtObservation": "AllDimensions"}
        if from_date:
            params["startPeriod"] = from_date.isoformat()[:7]
        try:
            kwargs_http = httpx_client_kwargs(foreign=True, timeout=httpx.Timeout(10.0, connect=4.0))
            async with httpx.AsyncClient(**kwargs_http) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                payload = resp.json()
            values = _sdmx_observations(payload)
            if not values:
                return self._timed_failure(start=start, error="Empty OECD series", error_code="EMPTY")
            series = MacroSeries(
                series_id=path,
                name=series_id,
                description="OECD SDMX",
                country="OECD",
                unit="varies",
                frequency="monthly",
                values=values,
                provider=self.name,
                source_url=url,
            )
            return FetchResult(success=True, data=series, provider=self.name, duration_ms=(time.perf_counter() - start) * 1000)
        except Exception as exc:
            return self._failure_from_exc(start, exc)


class EurostatLiveProvider(_MacroStubMixin, DataProvider):
    """Live Eurostat dissemination API; bulk zips remain a separate historical path."""

    def __init__(self, config: Optional[DataProviderConfig] = None):
        super().__init__(
            config
            or DataProviderConfig(
                name="eurostat",
                base_url="https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data",
                rate_limit=RateLimitConfig(requests_per_minute=20, burst_size=4),
                priority=66,
                timeout_seconds=8.0,
            )
        )

    @property
    def supported_data_types(self) -> list[DataType]:
        return [DataType.MACRO_SERIES]

    async def fetch_macro_series(
        self,
        series_id: str,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        **kwargs: Any,
    ) -> FetchResult:
        start = time.perf_counter()
        self._record_request()
        mapped = EUROSTAT_ALIASES.get(series_id.upper())
        dataset, extra = mapped if mapped else (series_id.lower(), {})
        url = f"{self.config.base_url}/{dataset}"
        params = {"format": "JSON", "lang": "EN", "lastTimePeriod": "48", **extra}
        try:
            kwargs_http = httpx_client_kwargs(foreign=True, timeout=httpx.Timeout(10.0, connect=4.0))
            async with httpx.AsyncClient(**kwargs_http) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                payload = resp.json()
            values = _jsonstat_time_values(payload)
            if not values:
                return self._timed_failure(start=start, error="Empty Eurostat series", error_code="EMPTY")
            series = MacroSeries(
                series_id=dataset,
                name=series_id,
                description="Eurostat live statistics API",
                country="EA",
                unit="%",
                frequency="varies",
                values=values,
                provider=self.name,
                source_url=url,
            )
            return FetchResult(success=True, data=series, provider=self.name, duration_ms=(time.perf_counter() - start) * 1000)
        except Exception as exc:
            return self._failure_from_exc(start, exc)


class EiaDataProvider(_MacroStubMixin, DataProvider):
    def __init__(self, config: Optional[DataProviderConfig] = None):
        super().__init__(
            config
            or DataProviderConfig(
                name="eia",
                api_key_env="EIA_API_KEY",
                requires_api_key=True,
                base_url="https://api.eia.gov/v2",
                rate_limit=RateLimitConfig(requests_per_minute=30, burst_size=5),
                priority=72,
                timeout_seconds=8.0,
            )
        )

    @property
    def supported_data_types(self) -> list[DataType]:
        return [DataType.MACRO_SERIES]

    async def fetch_macro_series(
        self,
        series_id: str,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        **kwargs: Any,
    ) -> FetchResult:
        start = time.perf_counter()
        self._record_request()
        if not self._api_key:
            return self._key_missing_result(start)
        sid = EIA_ALIASES.get(series_id.upper(), series_id)
        url = f"{self.config.base_url}/seriesid/{sid}"
        try:
            kwargs_http = httpx_client_kwargs(foreign=True, timeout=httpx.Timeout(10.0, connect=4.0))
            async with httpx.AsyncClient(**kwargs_http) as client:
                resp = await client.get(url, params={"api_key": settings.EIA_API_KEY.strip()})
                resp.raise_for_status()
                payload = resp.json()
            rows = (((payload.get("response") or {}).get("data")) or [])
            values = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                d = row.get("period") or row.get("date")
                v = row.get("value")
                if d is None or v in (None, ""):
                    continue
                values.append({"date": str(d), "value": float(v)})
            values.sort(key=lambda x: str(x["date"]))
            if not values:
                return self._timed_failure(start=start, error="Empty EIA series", error_code="EMPTY")
            series = MacroSeries(
                series_id=sid,
                name=series_id,
                description="EIA series",
                country="US",
                unit="USD",
                frequency="daily",
                values=values,
                provider=self.name,
                source_url=url,
            )
            return FetchResult(success=True, data=series, provider=self.name, duration_ms=(time.perf_counter() - start) * 1000)
        except Exception as exc:
            return self._failure_from_exc(start, exc)
