#!/usr/bin/env python3
"""One-shot: validate + connect Bybit from env (keys never in source)."""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, "/app")


async def main() -> None:
    from app.services.trading_keys.bybit_validator import validate_bybit_key
    from app.db.session import AsyncSessionLocal
    from app.services.portfolio.user_scope import get_user_by_email
    from app.services.trading_keys.service import connect_trading_account
    from app.services.execution.tokenized_provider_type import TOKENIZED_EQUITY_VENUE

    email = os.environ["APEX_USER_EMAIL"]
    api_key = os.environ["TOKENIZED_API_KEY"]
    api_secret = os.environ["TOKENIZED_API_SECRET"]

    v = await validate_bybit_key(api_key=api_key, api_secret=api_secret)
    print("validate_ok", v.ok, v.account_display or v.error)
    if not v.ok:
        sys.exit(1)

    creds = {"api_key": api_key, "api_secret": api_secret, "provider_type": "bybit"}
    async with AsyncSessionLocal() as db:
        user = await get_user_by_email(db, email)
        if not user:
            print("user_not_found", email)
            sys.exit(1)
        from app.db.rls import set_session_user_id

        await set_session_user_id(db, user.id)
        meta, validation = await connect_trading_account(
            db,
            user_id=user.id,
            venue=TOKENIZED_EQUITY_VENUE,
            credentials=creds,
            account_mode="live",
            provider_type="bybit",
            no_withdrawal_confirmed=True,
        )
        print("connect_ok", validation.ok, validation.account_display, getattr(meta, "id", None))


asyncio.run(main())
