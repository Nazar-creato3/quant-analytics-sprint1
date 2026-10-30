"""GA16-144: approval logs must not contain the user's email."""
from __future__ import annotations

from app.api.v1.endpoints.maneuvers import _log_actor


def test_log_actor_is_not_email() -> None:
    email = "alice@example.com"
    token = _log_actor(email)
    assert "@" not in token
    assert "alice" not in token
    assert token == _log_actor(email)
    assert token != _log_actor("bob@example.com")
