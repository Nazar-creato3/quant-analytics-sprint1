"""WebAuthn platform authenticator binding — one device per user."""
from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.domain.application_flow import WebAuthnCredentialORM
from app.utils.audit import audit
from app.utils.cache import cache_get, cache_set
from app.utils.helpers import new_uuid, utcnow

logger = get_logger(__name__)

_CHALLENGE_TTL = 300


def _challenge_key(user_id: str, purpose: str) -> str:
    return f"webauthn:{purpose}:{user_id}"


def _b64url_decode(value: str) -> bytes:
    pad = "=" * ((4 - len(value) % 4) % 4)
    return base64.urlsafe_b64decode(value + pad)


def _verify_assertion_signature(
    *,
    public_key: bytes,
    client_data_json: bytes,
    authenticator_data: bytes,
    signature: bytes,
) -> None:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

    if not signature or not authenticator_data:
        raise ValueError("assertion_signature_missing")
    signed = authenticator_data + hashlib.sha256(client_data_json).digest()
    try:
        key = serialization.load_der_public_key(public_key)
    except Exception as exc:
        raise ValueError("assertion_signature_invalid") from exc
    if not isinstance(key, ec.EllipticCurvePublicKey):
        raise ValueError("assertion_signature_invalid")
    attempts = [signature]
    if len(signature) == 64:
        attempts.append(
            encode_dss_signature(
                int.from_bytes(signature[:32], "big"),
                int.from_bytes(signature[32:], "big"),
            )
        )
    for blob in attempts:
        try:
            key.verify(blob, signed, ec.ECDSA(hashes.SHA256()))
            return
        except InvalidSignature:
            continue
    raise ValueError("assertion_signature_invalid")


class WebAuthnService:
    async def has_credential(self, db: AsyncSession, user_id: str) -> bool:
        result = await db.execute(
            select(WebAuthnCredentialORM.id).where(WebAuthnCredentialORM.user_id == user_id).limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def get_credential(self, db: AsyncSession, user_id: str) -> WebAuthnCredentialORM | None:
        result = await db.execute(
            select(WebAuthnCredentialORM).where(WebAuthnCredentialORM.user_id == user_id).limit(1)
        )
        return result.scalar_one_or_none()

    async def registration_options(self, db: AsyncSession, user_id: str, email: str) -> dict[str, Any]:
        import secrets

        challenge = secrets.token_urlsafe(32)
        await cache_set(_challenge_key(user_id, "register"), challenge, _CHALLENGE_TTL)
        return {
            "challenge": challenge,
            "rp": {"name": settings.WEBAUTHN_RP_NAME, "id": settings.WEBAUTHN_RP_ID},
            "user": {"id": base64.urlsafe_b64encode(user_id.encode()).decode().rstrip("="), "name": email, "displayName": email},
            "pubKeyCredParams": [{"type": "public-key", "alg": -7}, {"type": "public-key", "alg": -257}],
            "authenticatorSelection": {
                "authenticatorAttachment": "platform",
                "residentKey": "preferred",
                "userVerification": "required",
            },
            "timeout": 60000,
            "attestation": "none",
        }

    async def verify_registration(
        self,
        db: AsyncSession,
        user_id: str,
        credential: dict[str, Any],
    ) -> WebAuthnCredentialORM:
        expected = await cache_get(_challenge_key(user_id, "register"))
        if not expected:
            raise ValueError("registration_challenge_expired")

        if await self.has_credential(db, user_id):
            raise ValueError("credential_already_registered")

        client_data = json.loads(base64.urlsafe_b64decode(credential["response"]["clientDataJSON"] + "=="))
        if client_data.get("challenge") != expected:
            raise ValueError("challenge_mismatch")

        cred_id = credential.get("id") or credential.get("rawId")
        public_key = base64.urlsafe_b64decode(
            credential["response"]["publicKey"] + "=="
            if "publicKey" in credential["response"]
            else credential["response"]["attestationObject"] + "=="
        )

        row = WebAuthnCredentialORM(
            id=new_uuid(),
            user_id=user_id,
            credential_id=cred_id,
            public_key=public_key,
            sign_count=0,
        )
        db.add(row)
        await db.flush()
        return row

    async def assertion_options(self, db: AsyncSession, user_id: str) -> dict[str, Any]:
        import secrets

        cred = await self.get_credential(db, user_id)
        if not cred:
            raise ValueError("no_webauthn_credential")

        challenge = secrets.token_urlsafe(32)
        await cache_set(_challenge_key(user_id, "login"), challenge, _CHALLENGE_TTL)
        return {
            "challenge": challenge,
            "timeout": 60000,
            "rpId": settings.WEBAUTHN_RP_ID,
            "allowCredentials": [{"type": "public-key", "id": cred.credential_id}],
            "userVerification": "required",
        }

    async def verify_assertion(
        self,
        db: AsyncSession,
        user_id: str,
        credential: dict[str, Any],
    ) -> WebAuthnCredentialORM:
        expected = await cache_get(_challenge_key(user_id, "login"))
        if not expected:
            raise ValueError("assertion_challenge_expired")

        cred = await self.get_credential(db, user_id)
        if not cred:
            raise ValueError("no_webauthn_credential")

        cred_id = credential.get("id") or credential.get("rawId")
        if cred_id != cred.credential_id:
            raise ValueError("wrong_device")

        response = credential.get("response") or {}
        client_raw = _b64url_decode(str(response.get("clientDataJSON") or ""))
        client_data = json.loads(client_raw)
        if client_data.get("challenge") != expected:
            raise ValueError("challenge_mismatch")

        try:
            signature = _b64url_decode(str(response.get("signature") or ""))
            authenticator_data = _b64url_decode(str(response.get("authenticatorData") or ""))
        except Exception as exc:
            raise ValueError("assertion_signature_missing") from exc
        _verify_assertion_signature(
            public_key=bytes(cred.public_key),
            client_data_json=client_raw,
            authenticator_data=authenticator_data,
            signature=signature,
        )

        cred.sign_count += 1
        cred.last_used_at = utcnow()
        await db.flush()
        return cred

    async def release_device_binding(
        self,
        db: AsyncSession,
        user_id: str,
        *,
        actor_user_id: str | None = None,
    ) -> None:
        await db.execute(delete(WebAuthnCredentialORM).where(WebAuthnCredentialORM.user_id == user_id))
        await audit.log(
            db,
            action="webauthn_device_released",
            user_id=actor_user_id,
            resource_type="user",
            resource_id=user_id,
            details={},
        )
        await db.flush()


webauthn_service = WebAuthnService()
