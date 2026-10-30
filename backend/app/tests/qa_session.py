"""Test helpers: bind QA HTTP reads to a session user_id."""
from __future__ import annotations

from app.core.security import create_access_token
from app.main import app
from app.services.qa.session_user import require_session_identity, require_session_user_id


def bind_session_user(user_id: str) -> None:
    app.dependency_overrides[require_session_user_id] = lambda: user_id
    app.dependency_overrides[require_session_identity] = lambda: user_id


def clear_session_user() -> None:
    app.dependency_overrides.pop(require_session_user_id, None)
    app.dependency_overrides.pop(require_session_identity, None)


def auth_headers(user_id: str) -> dict[str, str]:
    token = create_access_token(user_id, extra_claims={"user_id": user_id})
    return {"Authorization": f"Bearer {token}"}
