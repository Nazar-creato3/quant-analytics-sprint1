"""GA16-249: pretrade logs must not contain the raw user_id."""
from __future__ import annotations

from app.services.pretrade.policy import _log_actor


def test_pretrade_log_actor_is_not_user_id() -> None:
    uid = "alice-user-99"
    token = _log_actor(uid)
    assert uid not in token
    assert "@" not in token
    assert token == _log_actor(uid)
    assert token != _log_actor("bob-user-1")
