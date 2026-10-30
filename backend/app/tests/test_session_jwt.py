"""Session JWT via PyJWT. Does not import app.main."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.core.config import settings
from app.core.security import JWTError, create_access_token, decode_token


def test_access_token_roundtrip():
    token = create_access_token("user@example.com")
    payload = decode_token(token)
    assert payload["sub"] == "user@example.com"
    assert payload["type"] == "access"
    assert "exp" in payload


def test_decode_rejects_wrong_algorithm():
    token = jwt.encode(
        {
            "sub": "user@example.com",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        settings.SECRET_KEY,
        algorithm="HS512",
    )
    with pytest.raises(JWTError):
        decode_token(token)


def test_decode_rejects_expired_token():
    token = jwt.encode(
        {
            "sub": "user@example.com",
            "exp": datetime.now(timezone.utc) - timedelta(minutes=5),
        },
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    with pytest.raises(JWTError):
        decode_token(token)


def test_decode_rejects_missing_sub():
    token = jwt.encode(
        {"exp": datetime.now(timezone.utc) + timedelta(minutes=5), "type": "access"},
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    with pytest.raises(JWTError):
        decode_token(token)
