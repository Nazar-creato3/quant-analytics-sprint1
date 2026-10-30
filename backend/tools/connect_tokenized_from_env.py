#!/usr/bin/env python3
"""Connect tokenized equity provider using env vars (never commit keys).

Usage on VPS:
  export APEX_USER_EMAIL=you@example.com
  export TOKENIZED_PROVIDER=bybit   # or mexc
  export TOKENIZED_API_KEY=...
  export TOKENIZED_API_SECRET=...
  python3 tools/connect_tokenized_from_env.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db.session import AsyncSessionLocal
from app.services.portfolio.user_scope import get_user_by_email  # type: ignore[attr-defined]
from app.services.trading_keys.service import connect_trading_account  # type: ignore[attr-defined]
from app.services.execution.tokenized_provider_type import TOKENIZED_EQUITY_VENUE, TokenizedProvider


async def main() -> None:
    email = os.environ.get("APEX_USER_EMAIL", "").strip()
    provider = TokenizedProvider.normalize(os.environ.get("TOKENIZED_PROVIDER", "bybit")).value
    api_key = os.environ.get("TOKENIZED_API_KEY", os.environ.get("BYBIT_API_KEY", "")).strip()
    api_secret = os.environ.get("TOKENIZED_API_SECRET", os.environ.get("BYBIT_API_SECRET", "")).strip()

    if not email or not api_key or not api_secret:
        print("Set APEX_USER_EMAIL, TOKENIZED_API_KEY, TOKENIZED_API_SECRET (and optional TOKENIZED_PROVIDER)")
        sys.exit(1)

    creds = {
        "api_key": api_key,
        "api_secret": api_secret,
        "provider_type": provider,
    }
    async with AsyncSessionLocal() as db:
        user = await get_user_by_email(db, email)
        if user is None:
            print(f"User not found: {email}")
            sys.exit(1)
        meta, validation = await connect_trading_account(
            db,
            user_id=user.id,
            venue=TOKENIZED_EQUITY_VENUE,
            credentials=creds,
            account_mode="live",
            provider_type=provider,
            no_withdrawal_confirmed=True,
        )
        if not validation.ok or meta is None:
            print("FAILED:", validation.error)
            sys.exit(1)
        print("OK:", validation.account_display, "provider=", provider, "key_id=", meta.id)


if __name__ == "__main__":
    asyncio.run(main())
