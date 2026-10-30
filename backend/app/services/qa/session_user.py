"""Session user_id for QA portfolio reads (E46-04). Query cannot spoof another user."""
from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException, Query, status

from app.core.deps import get_current_user_payload


def identity_from_payload(payload: dict[str, Any]) -> str:
    uid = payload.get("user_id")
    if isinstance(uid, str) and uid.strip():
        return uid.strip()
    subject = payload.get("sub")
    if isinstance(subject, str) and subject.strip():
        return subject.strip()
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


# Client-side placeholder: the UI and many request bodies default user_id to "demo"
# before the session is known. It names nobody, so it means "the session user".
_PLACEHOLDER_IDS = frozenset({"demo", ""})


def same_user(requested: str | None, session: str) -> str:
    if requested is not None and requested.strip() in _PLACEHOLDER_IDS:
        return session
    if requested and requested != session:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="user_id does not match session",
        )
    return session


async def require_session_identity(
    payload: dict[str, Any] = Depends(get_current_user_payload),
) -> str:
    return identity_from_payload(payload)


async def require_session_user_id(
    requested: str | None = Query(None, alias="user_id"),
    payload: dict[str, Any] = Depends(get_current_user_payload),
) -> str:
    return same_user(requested, identity_from_payload(payload))
