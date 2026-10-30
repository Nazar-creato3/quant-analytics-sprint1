#!/usr/bin/env python3
import asyncio
from sqlalchemy import select
from app.db.session import AsyncSessionLocal
from app.db.models import User

async def main():
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(User.email, User.id).limit(10))
        for row in r.all():
            print(row[0], row[1])

asyncio.run(main())
