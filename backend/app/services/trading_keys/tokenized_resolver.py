"""Resolve tokenized equity credentials (unified venue + provider_type)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.execution.tokenized_provider_type import TOKENIZED_EQUITY_VENUE, TokenizedProvider
from app.services.trading_keys.resolver import UserTradingKeyNotFound, UserVenueCredentials, get_active_user_credentials


@dataclass
class TokenizedEquityCredentials:
    key_id: str
    user_id: str
    account_mode: str
    provider_type: str
    credentials: dict[str, Any]
    account_display: str | None


async def get_tokenized_equity_credentials(
    db: AsyncSession,
    *,
    user_id: str,
    account_mode: str = "live",
    action: str = "order_execution",
) -> TokenizedEquityCredentials:
    """Load unified tokenized_equity key, with legacy bybit/mexc venue fallback."""
    last_exc: Exception | None = None
    for venue in (TOKENIZED_EQUITY_VENUE, "bybit", "mexc"):
        try:
            creds = await get_active_user_credentials(
                db,
                user_id=user_id,
                venue=venue,
                account_mode=account_mode,
                action=action,
            )
            provider_type = _resolve_provider_type(creds, venue)
            return TokenizedEquityCredentials(
                key_id=creds.key_id,
                user_id=creds.user_id,
                account_mode=creds.account_mode,
                provider_type=provider_type,
                credentials=creds.credentials,
                account_display=creds.account_display,
            )
        except UserTradingKeyNotFound as exc:
            last_exc = exc
            continue
    raise UserTradingKeyNotFound(str(last_exc or "No tokenized equity key"))


def _resolve_provider_type(creds: UserVenueCredentials, venue: str) -> str:
    payload = creds.credentials
    if payload.get("provider_type"):
        return TokenizedProvider.normalize(payload["provider_type"]).value
    if venue == "mexc":
        return TokenizedProvider.MEXC.value
    return TokenizedProvider.BYBIT.value
