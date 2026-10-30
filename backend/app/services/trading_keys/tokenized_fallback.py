"""Tokenized equity health — Bybit-only (MEXC deferred)."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.trading_accounts import TokenizedFallbackOut
from app.services.trading_keys.resolver import UserTradingKeyNotFound
from app.services.trading_keys.tokenized_resolver import get_tokenized_equity_credentials
from app.services.trading_keys.user_executor import resolve_account_mode
from app.services.trading_keys.validators import validate_venue_credentials

_PRIMARY = "bybit"


async def check_tokenized_fallback(
    db: AsyncSession,
    *,
    user_id: str,
    email: str,
) -> TokenizedFallbackOut:
    del email
    account_mode = resolve_account_mode()
    primary_healthy = False
    try:
        bundle = await get_tokenized_equity_credentials(
            db, user_id=user_id, account_mode=account_mode
        )
        if bundle.provider_type == _PRIMARY:
            v = await validate_venue_credentials(
                "tokenized_equity",
                bundle.credentials,
                provider_type=_PRIMARY,
                account_mode=account_mode,
            )
            primary_healthy = v.ok
    except UserTradingKeyNotFound:
        primary_healthy = False

    return TokenizedFallbackOut(
        primary_provider=_PRIMARY,
        primary_healthy=primary_healthy,
        alternate_provider=None,
        alternate_connected=False,
        suggest_switch=False,
        message=None,
    )
