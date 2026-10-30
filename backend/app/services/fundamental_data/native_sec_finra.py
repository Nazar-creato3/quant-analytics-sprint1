"""Native SEC EDGAR + FINRA short interest — no vendor SDK, no key."""
from __future__ import annotations

import time
from typing import Any, Optional

import httpx

from app.core.config import settings
from app.core.http_proxy import httpx_client_kwargs
from app.core.logging import get_logger
from app.services.fundamental_data.models import FinraShortInterestRecord, RegulatoryDataResult, SecFiling
from app.services.fundamental_data.provider import FundamentalDataProvider

logger = get_logger(__name__)

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
FINRA_SHORT_URL = "https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest"

_CIK_CACHE: dict[str, str] = {}
_TICKER_MAP_AT: float | None = None


def _user_agent() -> str:
    return (getattr(settings, "SEC_USER_AGENT", None) or "").strip() or (
        "QuantAnalytics/1.0 (research@quantanalyticsclub.ru)"
    )


def _sec_headers() -> dict[str, str]:
    return {
        "User-Agent": _user_agent(),
        "Accept": "application/json",
        "Accept-Encoding": "gzip, deflate",
    }


def pad_cik(cik: int | str) -> str:
    digits = "".join(ch for ch in str(cik) if ch.isdigit())
    return digits.zfill(10)


def _latest_fact_usd(facts: dict[str, Any], *concept_names: str) -> float | None:
    us_gaap = (facts.get("facts") or {}).get("us-gaap") or {}
    for name in concept_names:
        node = us_gaap.get(name) or {}
        units = node.get("units") or {}
        rows = units.get("USD") or units.get("USD/shares") or units.get("shares") or []
        if not rows:
            continue
        dated = [r for r in rows if isinstance(r, dict) and r.get("val") is not None]
        if not dated:
            continue
        dated.sort(key=lambda r: str(r.get("end") or r.get("filed") or ""), reverse=True)
        try:
            return float(dated[0]["val"])
        except (TypeError, ValueError):
            continue
    return None


class NativeSecFinraProvider(FundamentalDataProvider):
    """Direct data.sec.gov + FINRA REST. Always on."""

    @property
    def source_enabled(self) -> bool:
        return True

    async def _client(self) -> httpx.AsyncClient:
        kwargs = httpx_client_kwargs(foreign=True, timeout=httpx.Timeout(12.0, connect=4.0))
        return httpx.AsyncClient(**kwargs)

    async def resolve_cik(self, ticker: str) -> str | None:
        global _TICKER_MAP_AT
        import time as _time

        symbol = ticker.strip().upper()
        if symbol in _CIK_CACHE:
            return _CIK_CACHE[symbol]
        # The SEC ticker file (~1 MB) was downloaded again for every unknown symbol (all MOEX
        # and crypto tickers): load it once a day and answer misses from memory.
        if _TICKER_MAP_AT is None or _time.monotonic() - _TICKER_MAP_AT > 86_400:
            async with await self._client() as client:
                resp = await client.get(SEC_TICKERS_URL, headers=_sec_headers())
                resp.raise_for_status()
                payload = resp.json()
            if not isinstance(payload, dict):
                return None
            for row in payload.values():
                if not isinstance(row, dict):
                    continue
                cik = pad_cik(row.get("cik_str") or row.get("cik") or "")
                sym = str(row.get("ticker") or "").upper()
                if sym and cik.strip("0"):
                    _CIK_CACHE[sym] = cik
            _TICKER_MAP_AT = _time.monotonic()
        return _CIK_CACHE.get(symbol)

    async def get_company_facts(self, ticker: str) -> dict[str, Any]:
        cik = await self.resolve_cik(ticker)
        if not cik:
            return {}
        async with await self._client() as client:
            resp = await client.get(SEC_FACTS_URL.format(cik=cik), headers=_sec_headers())
            if resp.status_code == 404:
                return {"cik": cik}
            resp.raise_for_status()
            facts = resp.json()
        shares = _latest_fact_usd(facts, "EntityCommonStockSharesOutstanding", "CommonStockSharesOutstanding")
        ebit = _latest_fact_usd(facts, "OperatingIncomeLoss")
        revenue = _latest_fact_usd(facts, "Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax")
        equity = _latest_fact_usd(facts, "StockholdersEquity")
        net_income = _latest_fact_usd(facts, "NetIncomeLoss")
        assets = _latest_fact_usd(facts, "Assets")
        return {
            "cik": cik,
            "shares_outstanding": shares,
            "revenue": revenue,
            "net_income": net_income,
            "equity": equity,
            "assets": assets,
            "operating_income": ebit,
            "roe": (net_income / equity) if net_income is not None and equity else None,
            "profit_margin": (net_income / revenue) if net_income is not None and revenue else None,
        }

    async def get_sec_filings(
        self,
        ticker: str,
        *,
        limit: int = 20,
        form_type: Optional[str] = None,
    ) -> RegulatoryDataResult:
        start = time.perf_counter()
        symbol = ticker.strip().upper()
        try:
            cik = await self.resolve_cik(symbol)
            if not cik:
                return self._fail(start, "Эмитент не найден в реестре SEC", "NOT_FOUND", symbol)
            async with await self._client() as client:
                resp = await client.get(SEC_SUBMISSIONS_URL.format(cik=cik), headers=_sec_headers())
                resp.raise_for_status()
                data = resp.json()
            recent = (data.get("filings") or {}).get("recent") or {}
            forms = recent.get("form") or []
            filed = recent.get("filingDate") or []
            accepted = recent.get("acceptanceDateTime") or []
            acc = recent.get("accessionNumber") or []
            docs = recent.get("primaryDocument") or []
            wanted = (form_type or "").strip().upper()
            rows: list[dict[str, Any]] = []
            for i, form in enumerate(forms):
                if wanted and str(form).upper() != wanted:
                    continue
                accession = str(acc[i] if i < len(acc) else "").replace("-", "")
                doc = docs[i] if i < len(docs) else ""
                link = (
                    f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession}/{doc}"
                    if accession and doc
                    else None
                )
                rows.append(
                    SecFiling(
                        symbol=symbol,
                        form_type=str(form),
                        filing_date=str(filed[i]) if i < len(filed) else None,
                        accepted_date=str(accepted[i])[:10] if i < len(accepted) else None,
                        link=link,
                        cik=cik,
                    ).model_dump()
                )
                if len(rows) >= limit:
                    break
            facts = await self.get_company_facts(symbol)
            return RegulatoryDataResult(
                success=True,
                data={
                    "symbol": symbol,
                    "filings": rows,
                    "count": len(rows),
                    "company_facts": facts,
                },
                source_enabled=True,
                duration_ms=(time.perf_counter() - start) * 1000,
                metadata={"ticker": symbol},
            )
        except Exception as exc:
            logger.warning("native_sec_filings_failed", ticker=symbol, error=str(exc)[:200])
            return self._fail(start, "Регуляторные данные временно недоступны", "UPSTREAM_ERROR", symbol)

    async def get_finra_short_interest(
        self,
        ticker: str,
        *,
        limit: int = 12,
    ) -> RegulatoryDataResult:
        start = time.perf_counter()
        symbol = ticker.strip().upper()
        body = {
            "compareFilters": [
                {
                    "fieldName": "issueSymbolIdentifier",
                    "compareType": "EQUAL",
                    "fieldValue": symbol,
                }
            ],
            "limit": max(1, min(limit, 52)),
        }
        try:
            async with await self._client() as client:
                resp = await client.post(
                    FINRA_SHORT_URL,
                    json=body,
                    headers={"Accept": "application/json", "Content-Type": "application/json"},
                )
                resp.raise_for_status()
                payload = resp.json()
            raw_rows = payload if isinstance(payload, list) else payload.get("data") or payload.get("records") or []
            records: list[dict[str, Any]] = []
            for row in raw_rows[:limit]:
                if not isinstance(row, dict):
                    continue
                current = row.get("currentShortPositionQuantity") or row.get("current_short_position")
                previous = row.get("previousShortPositionQuantity") or row.get("previous_short_position")
                dtc = row.get("daysToCoverQuantity") or row.get("days_to_cover")
                vol = row.get("averageDailyVolumeQuantity") or row.get("avg_daily_share_volume")
                rec = FinraShortInterestRecord(
                    symbol=symbol,
                    settlement_date=str(
                        row.get("settlementDate") or row.get("settlement_date") or ""
                    ) or None,
                    current_short_position=float(current) if current is not None else None,
                    previous_short_position=float(previous) if previous is not None else None,
                    days_to_cover=float(dtc) if dtc is not None else None,
                    avg_daily_share_volume=float(vol) if vol is not None else None,
                )
                records.append(rec.model_dump())
            squeeze = None
            if records:
                dtc = records[0].get("days_to_cover")
                if isinstance(dtc, (int, float)):
                    if dtc >= 8:
                        squeeze = "short_interest_elevated"
                    elif dtc <= 2:
                        squeeze = "short_interest_light"
                    else:
                        squeeze = "short_interest_typical"
            return RegulatoryDataResult(
                success=True,
                data={
                    "symbol": symbol,
                    "records": records,
                    "count": len(records),
                    "short_pressure": squeeze,
                },
                source_enabled=True,
                duration_ms=(time.perf_counter() - start) * 1000,
                metadata={"ticker": symbol},
            )
        except Exception as exc:
            logger.warning("native_finra_failed", ticker=symbol, error=str(exc)[:200])
            return self._fail(start, "Регуляторные данные временно недоступны", "UPSTREAM_ERROR", symbol)

    def _fail(self, start: float, message: str, code: str, symbol: str) -> RegulatoryDataResult:
        return RegulatoryDataResult(
            success=False,
            error=message,
            error_code=code,
            source_enabled=True,
            duration_ms=(time.perf_counter() - start) * 1000,
            metadata={"ticker": symbol},
        )
