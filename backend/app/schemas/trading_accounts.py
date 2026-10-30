"""Pydantic schemas for trading accounts API."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

VenueId = Literal["binance", "bybit", "mexc", "tokenized_equity", "alpaca", "tinkoff", "tbank", "finam"]
TokenizedProviderType = Literal["bybit", "mexc"]
AccountMode = Literal["paper", "live"]


class TradingAccountOut(BaseModel):
    id: str
    venue: str
    provider_type: str | None = None
    account_mode: AccountMode
    status: str
    label: str | None = None
    account_display: str | None = None
    permission_check_status: str
    withdraw_allowed: bool | None = None
    permission_warning: str | None = None
    last_health_at: datetime | None = None
    last_health_status: str | None = None
    rotation_due_at: datetime
    connected: bool = True


class ConnectRawKeyIn(BaseModel):
    venue: VenueId
    provider_type: TokenizedProviderType | None = None
    account_mode: AccountMode = "paper"
    api_key: str = Field(min_length=8)
    api_secret: str = Field(min_length=8)
    label: str | None = None
    no_withdrawal_confirmed: bool = False
    base_url: str | None = None
    reauth_token: str | None = None


class ConnectTokenIn(BaseModel):
    venue: VenueId
    account_mode: AccountMode = "paper"
    token: str = Field(min_length=8)
    label: str | None = None
    no_withdrawal_confirmed: bool = False
    reauth_token: str | None = None
    # Separate consent to process the broker account data (lawyer decision L-06).
    consent_broker: bool = False


class ConnectResultOut(BaseModel):
    ok: bool
    account: TradingAccountOut | None = None
    error: str | None = None
    account_display: str | None = None


class VenueCardOut(BaseModel):
    venue: str
    title: str
    description: str
    connection_type: Literal["oauth", "raw_key", "token"]
    setup_url: str | None = None
    setup_steps: list[str] = Field(default_factory=list)
    provider_options: list[TokenizedProviderType] = Field(default_factory=list)
    connected_accounts: list[TradingAccountOut] = Field(default_factory=list)
    featured: bool = False


class TradingAccountsOverviewOut(BaseModel):
    venues: list[VenueCardOut]
    rotation_reminders: list[TradingAccountOut] = Field(default_factory=list)
    demo_mode_available: bool = True
    tokenized_equity_provider: TokenizedProviderType = "bybit"


class TokenizedFallbackOut(BaseModel):
    primary_provider: TokenizedProviderType
    primary_healthy: bool
    alternate_provider: TokenizedProviderType | None = None
    alternate_connected: bool = False
    suggest_switch: bool = False
    message: str | None = None
