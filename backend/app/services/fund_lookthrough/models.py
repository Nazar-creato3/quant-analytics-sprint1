"""In-memory rows for fund_holdings / fund_meta (prompt 61)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


STALE_DAYS = 95
MAX_DEPTH = 3


@dataclass(frozen=True)
class FundHolding:
    fund_figi: str
    as_of: date
    holding_isin: str
    holding_name: str
    weight: Decimal
    asset_class: str
    currency: str
    source_url: str
    issuer: str
    sector: str
    country: str
    is_fund: bool = False
    child_figi: str | None = None


@dataclass(frozen=True)
class FundMeta:
    fund_figi: str
    index_code: str | None
    ter: Decimal | None
    as_of: date
    source: str
    composition_note: str
    source_url: str
    ticker: str
