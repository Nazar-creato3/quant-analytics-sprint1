"""Composite regulatory provider: native SEC/FINRA first, optional sidecar second."""
from __future__ import annotations

from app.core.config import get_settings
from app.services.fundamental_data.native_sec_finra import NativeSecFinraProvider
from app.services.fundamental_data.openbb_adapter import build_openbb_provider
from app.services.fundamental_data.provider import FundamentalDataProvider
from app.services.fundamental_data.models import RegulatoryDataResult


class CompositeRegulatoryProvider(FundamentalDataProvider):
    def __init__(self, *, use_sidecar: bool) -> None:
        self._native = NativeSecFinraProvider()
        self._sidecar = build_openbb_provider() if use_sidecar else None

    @property
    def source_enabled(self) -> bool:
        return True

    async def get_sec_filings(self, ticker: str, *, limit: int = 20, form_type: str | None = None) -> RegulatoryDataResult:
        native = await self._native.get_sec_filings(ticker, limit=limit, form_type=form_type)
        if native.success and native.data and (native.data.get("filings") or native.data.get("company_facts")):
            return native
        if self._sidecar is None:
            return native
        side = await self._sidecar.get_sec_filings(ticker, limit=limit, form_type=form_type)
        if side.success:
            merged = dict(side.data or {})
            if native.success and isinstance(native.data, dict):
                merged.setdefault("company_facts", native.data.get("company_facts"))
            side.data = merged
        return side if side.success else native

    async def get_finra_short_interest(self, ticker: str, *, limit: int = 12) -> RegulatoryDataResult:
        native = await self._native.get_finra_short_interest(ticker, limit=limit)
        if native.success and native.data and native.data.get("records"):
            return native
        if self._sidecar is None:
            return native
        side = await self._sidecar.get_finra_short_interest(ticker, limit=limit)
        return side if side.success else native
