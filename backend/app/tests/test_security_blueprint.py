"""Enforceable checks for security-architecture-blueprint items."""
from __future__ import annotations

import secrets

import pytest

from app.core.config import Settings, AppEnv
from app.core.field_encryption import decrypt_field, encrypt_field


def test_production_rejects_debug_and_plain_passwords():
    key = secrets.token_hex(32)
    with pytest.raises(Exception) as exc:
        Settings(
            APP_ENV=AppEnv.PRODUCTION,
            SECRET_KEY=key,
            DEBUG=True,
            PASSWORD_DEV_PLAIN=False,
            CSRF_PROTECTION_ENABLED=True,
        )
    assert "DEBUG" in str(exc.value)


def test_password_dev_plain_defaults_false():
    assert Settings.model_fields["PASSWORD_DEV_PLAIN"].default is False
    compose = (
        __import__("pathlib")
        .Path(__file__)
        .resolve()
        .parents[3]
        .joinpath("docker-compose.yml")
        .read_text(encoding="utf-8")
    )
    assert "PASSWORD_DEV_PLAIN:-false" in compose


def test_production_accepts_hardened_flags_from_env():
    key = secrets.token_hex(32)
    settings = Settings(
        APP_ENV=AppEnv.PRODUCTION,
        SECRET_KEY=key,
        DEBUG=False,
        PASSWORD_DEV_PLAIN=False,
        CSRF_PROTECTION_ENABLED=True,
    )
    assert settings.PASSWORD_DEV_PLAIN is False
    assert settings.CSRF_PROTECTION_ENABLED is True


def test_development_hash_is_not_plaintext_when_flag_off(monkeypatch):
    from app.core import config as config_mod
    from app.core.security import hash_password

    monkeypatch.setattr(config_mod.settings, "APP_ENV", AppEnv.DEVELOPMENT)
    monkeypatch.setattr(config_mod.settings, "PASSWORD_DEV_PLAIN", False)
    hashed = hash_password("secret-pass")
    assert not hashed.startswith("dev::")


def test_argon2_hash_roundtrip_when_dev_plain_disabled(monkeypatch):
    argon2 = pytest.importorskip("argon2")
    _ = argon2  # noqa: F841
    from app.core import config as config_mod
    from app.core.security import hash_password, verify_password

    monkeypatch.setattr(config_mod.settings, "APP_ENV", AppEnv.STAGING)
    monkeypatch.setattr(config_mod.settings, "PASSWORD_DEV_PLAIN", False)
    hashed = hash_password("Str0ng-Pass!")
    assert hashed.startswith("$argon2")
    assert verify_password("Str0ng-Pass!", hashed)
    assert not verify_password("wrong", hashed)


def test_bcrypt_legacy_hash_roundtrip(monkeypatch):
    bcrypt = pytest.importorskip("bcrypt")
    from app.core import config as config_mod
    from app.core.security import verify_password

    monkeypatch.setattr(config_mod.settings, "APP_ENV", AppEnv.PRODUCTION)
    monkeypatch.setattr(config_mod.settings, "PASSWORD_DEV_PLAIN", False)
    legacy = bcrypt.hashpw(b"Str0ng-Pass!", bcrypt.gensalt(rounds=12)).decode()
    assert legacy.startswith("$2b$")
    assert verify_password("Str0ng-Pass!", legacy)
    assert not verify_password("wrong", legacy)


def test_field_encryption_roundtrip(monkeypatch):
    import base64
    import os

    from app.core import config as config_mod

    key = base64.urlsafe_b64encode(os.urandom(32)).decode()
    monkeypatch.setattr(config_mod.settings, "FIELD_ENCRYPTION_KEY", key)
    ct = encrypt_field("broker-token-secret")
    assert ct != "broker-token-secret"
    assert decrypt_field(ct) == "broker-token-secret"
