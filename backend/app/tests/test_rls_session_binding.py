"""Plain get_db sessions must carry the signed-in user for row-level security, across commits."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core import deps
from app.db import rls


@pytest.mark.asyncio
async def test_set_session_user_id_reapplies_after_commit() -> None:
    db = MagicMock()
    db.sync_session = MagicMock()
    db.sync_session.info = {}
    db.execute = AsyncMock()
    calls = []
    import sqlalchemy

    orig = sqlalchemy.event.listen
    sqlalchemy.event.listen = lambda target, name, fn: calls.append((target, name, fn))
    try:
        await rls.set_session_user_id(db, "u-1")
    finally:
        sqlalchemy.event.listen = orig
    assert db.sync_session.info["rls_user_id"] == "u-1"
    assert calls and calls[0][1] == "after_begin"
    conn = MagicMock()
    calls[0][2](db.sync_session, None, conn)  # a new transaction after commit
    assert conn.execute.call_args[0][1] == {"uid": "u-1"}


@pytest.mark.asyncio
async def test_rls_user_from_request(monkeypatch) -> None:
    deps._RLS_UID_CACHE.clear()
    monkeypatch.setattr(deps, "decode_token", lambda tok: {"sub": "Alice@x.ru", "type": "access"})
    session = MagicMock()
    res = MagicMock()
    res.scalar_one_or_none.return_value = "uid-alice"
    session.execute = AsyncMock(return_value=res)
    req = MagicMock()
    req.headers = {"authorization": "Bearer abc"}
    assert await deps._rls_user_id_from_request(session, req) == "uid-alice"
    req.headers = {}
    assert await deps._rls_user_id_from_request(session, req) is None
    monkeypatch.setattr(deps, "decode_token", lambda tok: {"sub": "a@x.ru", "type": "refresh"})
    req.headers = {"authorization": "Bearer abc"}
    assert await deps._rls_user_id_from_request(session, req) is None
