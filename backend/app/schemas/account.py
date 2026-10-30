"""Personal cabinet (account) API schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class AccountUserOut(BaseModel):
    id: str
    email: str
    name: str = Field(..., description="Display name derived from email")
    role: str
    created_at: datetime
    last_login: Optional[datetime] = None


class AccountBalanceOut(BaseModel):
    total_usd: float
    free_usd: float = Field(..., description="Available / unallocated cash")
    locked_usd: float = Field(..., description="Capital in open positions")
    currency: str = "USD"
    mode: str = Field(..., description="paper | live")
    is_paper: bool = True
    as_of: str


class PortfolioPositionOut(BaseModel):
    ticker: str
    market_value_usd: Optional[float] = None
    side: str
    position_count: int = 1


class PortfolioOut(BaseModel):
    id: str
    name: str
    mode: str
    base_currency: str = "USD"
    market_value_usd: Optional[float] = None
    positions: list[PortfolioPositionOut] = Field(default_factory=list)


class AccountSummaryOut(BaseModel):
    user: AccountUserOut
    balance: AccountBalanceOut
    portfolios: list[PortfolioOut] = Field(default_factory=list)


class PaperTransferIn(BaseModel):
    amount_usd: float = Field(..., gt=0, le=10_000_000, description="Transfer amount in USD")
    reauth_token: str | None = None


class PaperTransferOut(BaseModel):
    transaction_type: str = Field(..., description="deposit | withdraw")
    amount_usd: float
    balance: AccountBalanceOut
    message: str
