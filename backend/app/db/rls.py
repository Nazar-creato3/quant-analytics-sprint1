"""Postgres row-level security session helpers."""
from __future__ import annotations

from typing import Any

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession

_RLS_SQL = text("SELECT set_config('app.user_id', :uid, true)")


def _after_begin(session: Any, _transaction: Any, connection: Any) -> None:
    uid = session.info.get("rls_user_id")
    if uid is not None:
        connection.execute(_RLS_SQL, {"uid": uid})


async def set_session_user_id(db: AsyncSession, user_id: str | None) -> None:
    """Bind app.user_id for this session.

    set_config(..., true) lasts one transaction only; after a commit the next transaction
    would run without a user and RLS would hide every row. The id is kept on the session and
    re-applied at the start of each new transaction.
    """
    uid = user_id or ""
    try:
        sync = db.sync_session
        sync.info["rls_user_id"] = uid
        if not sync.info.get("rls_listener"):
            event.listen(sync, "after_begin", _after_begin)
            sync.info["rls_listener"] = True
    except Exception:  # noqa: BLE001 — test doubles without a real session
        pass
    await db.execute(_RLS_SQL, {"uid": uid})
