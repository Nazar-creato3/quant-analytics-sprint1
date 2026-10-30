"""Disabled regulatory provider — returned when ENABLE_OPENBB_SOURCE=false."""

from __future__ import annotations

from typing import Optional

from app.services.fundamental_data.models import RegulatoryDataResult
from app.services.fundamental_data.provider import FundamentalDataProvider

_UNAVAILABLE_MSG = "Регуляторные данные временно недоступны"
_ERROR_CODE = "SOURCE_DISABLED"


class DisabledFundamentalDataProvider(FundamentalDataProvider):
    @property
    def source_enabled(self) -> bool:
        return False

    async def get_sec_filings(
        self,
        ticker: str,
        *,
        limit: int = 20,
        form_type: Optional[str] = None,
    ) -> RegulatoryDataResult:
        return RegulatoryDataResult(
            success=False,
            error=_UNAVAILABLE_MSG,
            error_code=_ERROR_CODE,
            source_enabled=False,
            metadata={"ticker": ticker.strip().upper()},
        )

    async def get_finra_short_interest(
        self,
        ticker: str,
        *,
        limit: int = 12,
    ) -> RegulatoryDataResult:
        return RegulatoryDataResult(
            success=False,
            error=_UNAVAILABLE_MSG,
            error_code=_ERROR_CODE,
            source_enabled=False,
            metadata={"ticker": ticker.strip().upper()},
        )
