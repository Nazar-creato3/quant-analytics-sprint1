"""Runtime secrets resolution (env today, Vault-compatible interface)."""
from __future__ import annotations

import os
from typing import Protocol

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class SecretsProvider(Protocol):
    def get_secret(self, key: str, *, default: str = "") -> str: ...


class EnvSecretsProvider:
    """Load secrets from process environment (never from committed files)."""

    def get_secret(self, key: str, *, default: str = "") -> str:
        return os.environ.get(key, default)


class VaultSecretsProvider:
    """
    HashiCorp Vault KV v2 reader (self-hosted target from security blueprint).

    Requires VAULT_ADDR, VAULT_TOKEN, and VAULT_SECRET_PATH settings.
    """

    def __init__(self, *, addr: str, token: str, mount_path: str) -> None:
        self._addr = addr.rstrip("/")
        self._token = token
        self._mount_path = mount_path.strip("/")

    def get_secret(self, key: str, *, default: str = "") -> str:
        import httpx

        url = f"{self._addr}/v1/{self._mount_path}"
        try:
            resp = httpx.get(
                url,
                headers={"X-Vault-Token": self._token},
                timeout=5.0,
            )
            resp.raise_for_status()
            data = resp.json().get("data", {}).get("data", {})
            return str(data.get(key, default))
        except Exception as exc:
            logger.error("Vault secret fetch failed", key=key, error=str(exc))
            return default


_provider: SecretsProvider | None = None


def get_secrets_provider() -> SecretsProvider:
    global _provider
    if _provider is not None:
        return _provider
    backend = settings.SECRETS_BACKEND.lower()
    if backend == "vault" and settings.VAULT_ADDR and settings.VAULT_TOKEN:
        _provider = VaultSecretsProvider(
            addr=settings.VAULT_ADDR,
            token=settings.VAULT_TOKEN,
            mount_path=settings.VAULT_SECRET_PATH,
        )
    else:
        _provider = EnvSecretsProvider()
    return _provider
