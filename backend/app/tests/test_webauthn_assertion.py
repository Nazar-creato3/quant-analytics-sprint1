"""GA16-294: WebAuthn login must verify the assertion signature."""
from __future__ import annotations

import base64
import hashlib
import json
from unittest.mock import AsyncMock, patch

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.domain.application_flow import WebAuthnCredentialORM
from app.services.webauthn.service import webauthn_service


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _pair():
    private = ec.generate_private_key(ec.SECP256R1())
    public_der = private.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private, public_der


def _assertion(private, *, challenge: str, authenticator_data: bytes | None = None) -> dict:
    client = json.dumps({"type": "webauthn.get", "challenge": challenge, "origin": "https://example.test"}).encode()
    auth = authenticator_data if authenticator_data is not None else b"\x00" * 37
    signed = auth + hashlib.sha256(client).digest()
    signature = private.sign(signed, ec.ECDSA(hashes.SHA256()))
    return {
        "id": "bound-credential-id",
        "response": {
            "clientDataJSON": _b64url(client),
            "authenticatorData": _b64url(auth),
            "signature": _b64url(signature),
        },
    }


@pytest.mark.asyncio
async def test_matching_challenge_without_signature_is_rejected():
    private, public_der = _pair()
    db = AsyncMock()
    bound = WebAuthnCredentialORM(
        id="cred-row-1",
        user_id="user-1",
        credential_id="bound-credential-id",
        public_key=public_der,
        sign_count=0,
    )
    client = json.dumps({"challenge": "challenge-123"}).encode()
    with (
        patch.object(webauthn_service, "get_credential", new=AsyncMock(return_value=bound)),
        patch("app.services.webauthn.service.cache_get", new=AsyncMock(return_value="challenge-123")),
    ):
        with pytest.raises(ValueError, match="assertion_signature"):
            await webauthn_service.verify_assertion(
                db,
                "user-1",
                {
                    "id": "bound-credential-id",
                    "response": {"clientDataJSON": _b64url(client)},
                },
            )


@pytest.mark.asyncio
async def test_valid_assertion_signature_is_accepted():
    private, public_der = _pair()
    db = AsyncMock()
    bound = WebAuthnCredentialORM(
        id="cred-row-1",
        user_id="user-1",
        credential_id="bound-credential-id",
        public_key=public_der,
        sign_count=0,
    )
    payload = _assertion(private, challenge="challenge-123")
    with (
        patch.object(webauthn_service, "get_credential", new=AsyncMock(return_value=bound)),
        patch("app.services.webauthn.service.cache_get", new=AsyncMock(return_value="challenge-123")),
    ):
        row = await webauthn_service.verify_assertion(db, "user-1", payload)
    assert row.sign_count == 1
    db.flush.assert_awaited()


@pytest.mark.asyncio
async def test_wrong_signature_is_rejected():
    private, public_der = _pair()
    other, _ = _pair()
    db = AsyncMock()
    bound = WebAuthnCredentialORM(
        id="cred-row-1",
        user_id="user-1",
        credential_id="bound-credential-id",
        public_key=public_der,
        sign_count=0,
    )
    payload = _assertion(other, challenge="challenge-123")
    with (
        patch.object(webauthn_service, "get_credential", new=AsyncMock(return_value=bound)),
        patch("app.services.webauthn.service.cache_get", new=AsyncMock(return_value="challenge-123")),
    ):
        with pytest.raises(ValueError, match="assertion_signature_invalid"):
            await webauthn_service.verify_assertion(db, "user-1", payload)
