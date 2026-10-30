"""Allow-list for decrypting trading credentials. Never log secret material."""
from __future__ import annotations

from threading import Lock
from typing import Any

ALLOWED_PURPOSES = frozenset({"execution", "health_check", "privacy_erase", "connect"})


class KeyAccessDenied(PermissionError):
    pass


_lock = Lock()
_log: list[dict[str, Any]] = []


def reset_access_log() -> None:
    with _lock:
        _log.clear()


def assert_purpose(purpose: str) -> None:
    if purpose not in ALLOWED_PURPOSES:
        raise KeyAccessDenied(f"trading key decrypt denied for purpose={purpose}")


def record_access(*, user_id: str | None, key_id: str, purpose: str) -> None:
    assert_purpose(purpose)
    with _lock:
        _log.append({"user_id": user_id, "key_id": key_id, "purpose": purpose})


def access_log() -> list[dict[str, Any]]:
    with _lock:
        return [dict(row) for row in _log]
