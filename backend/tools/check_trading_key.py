#!/usr/bin/env python3
import asyncio
from sqlalchemy import select, text
from app.db.session import AsyncSessionLocal
from app.db.rls import set_session_user_id
from app.domain.trading_keys import TradingKeyMetadataORM

USER_ID = "56926315-19e2-4832-8d39-ca1317c65e97"

async def main():
    async with AsyncSessionLocal() as db:
        await set_session_user_id(db, USER_ID)
        r = await db.execute(
            select(TradingKeyMetadataORM).where(
                TradingKeyMetadataORM.user_id == USER_ID,
                TradingKeyMetadataORM.venue.in_(["tokenized_equity", "bybit"]),
            )
        )
        rows = r.scalars().all()
        for row in rows:
            print(row.venue, row.provider_type, row.account_display, row.status)
        if not rows:
            print("NO_ROWS")

asyncio.run(main())
