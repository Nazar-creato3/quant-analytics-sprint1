"""Abstract regulatory data provider — the only interface the rest of the platform uses."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from app.services.fundamental_data.models import RegulatoryDataResult


class FundamentalDataProvider(ABC):
    """Internal abstraction for SEC filings and FINRA short-interest data."""

    @property
    @abstractmethod
    def source_enabled(self) -> bool:
        """Whether the upstream regulatory source is configured and enabled."""

    @abstractmethod
    async def get_sec_filings(
        self,
        ticker: str,
        *,
        limit: int = 20,
        form_type: Optional[str] = None,
    ) -> RegulatoryDataResult:
        ...

    @abstractmethod
    async def get_finra_short_interest(
        self,
        ticker: str,
        *,
        limit: int = 12,
    ) -> RegulatoryDataResult:
        ...
