#!/usr/bin/env python3
import asyncio
from app.db.session import AsyncSessionLocal
from app.db.rls import set_session_user_id
from app.services.trading_keys.tokenized_resolver import get_tokenized_equity_credentials
from app.services.execution.providers.factory import build_tokenized_equity_provider
from app.services.execution.providers.registry import get_execution_provider_for_user

USER_ID = "56926315-19e2-4832-8d39-ca1317c65e97"

async def main():
    async with AsyncSessionLocal() as db:
        await set_session_user_id(db, USER_ID)
        bundle = await get_tokenized_equity_credentials(db, user_id=USER_ID)
        print("provider_type", bundle.provider_type)
        provider = build_tokenized_equity_provider(bundle.provider_type, bundle.credentials)
        bal = await provider.get_account_balance()
        print("balance_usd", bal.total_usd, "source", bal.source)
        prov2, mode = await get_execution_provider_for_user(db, user_id=USER_ID, ticker="AAPL")
        print("registry_mode", mode.value, "provider", type(prov2).__name__)

asyncio.run(main())
