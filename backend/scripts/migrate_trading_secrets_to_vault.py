#!/usr/bin/env python3
"""Migrate trading venue keys from process env into Vault KV (never prints secret values)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.config import settings  # noqa: E402
from app.core.secrets_provider import (  # noqa: E402
    TRADING_SECRET_KEYS,
    VaultSecretsProvider,
    get_secrets_provider,
)


def _collect_from_env() -> dict[str, str]:
    payload: dict[str, str] = {}
    for key in TRADING_SECRET_KEYS:
        value = os.environ.get(key, "").strip()
        if value:
            payload[key] = value
    return payload


def main() -> int:
    backend = (settings.SECRETS_BACKEND or "env").lower().strip()
    if backend != "vault":
        print("SECRETS_BACKEND is not vault; set SECRETS_BACKEND=vault first", file=sys.stderr)
        return 2
    if not settings.VAULT_ADDR or not settings.VAULT_TOKEN:
        print("VAULT_ADDR and VAULT_TOKEN must be configured", file=sys.stderr)
        return 2

    provider = get_secrets_provider()
    if not isinstance(provider, VaultSecretsProvider):
        print("Vault provider unavailable", file=sys.stderr)
        return 2

    health = provider.health()
    if health.get("sealed"):
        print(json.dumps({"status": "vault_sealed", "vault": health}, indent=2))
        return 1
    if not health.get("initialized"):
        print(json.dumps({"status": "vault_not_initialized", "vault": health}, indent=2))
        return 1

    from app.services.trading_keys.vault_paths import legacy_global_trading_path
    from app.services.trading_keys.vault_store import vault_fetch_diagnostics

    path_diag = vault_fetch_diagnostics(legacy_global_trading_path())
    if path_diag.get("http_status") == 400:
        print(
            json.dumps(
                {
                    "status": "vault_path_invalid",
                    "hint": "Check VAULT_SECRET_PATH (KV v2: secret/data/...) and token whitespace",
                    "path_diagnostic": path_diag,
                    "vault": health,
                },
                indent=2,
            )
        )
        return 1

    payload = _collect_from_env()
    if not payload:
        print(json.dumps({"status": "no_env_keys", "vault": health}, indent=2))
        return 1

    try:
        written = provider.put_secrets(payload, merge=True)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "vault_write_failed",
                    "error": str(exc)[:300],
                    "vault": health,
                    "secret_path": settings.VAULT_SECRET_PATH,
                },
                indent=2,
            )
        )
        return 1

    after = provider.health()
    report = {
        "status": "migrated",
        "keys_written": written,
        "keys_present_in_vault": after.get("keys_present", []),
        "secret_path": settings.VAULT_SECRET_PATH,
        "path_diagnostic": path_diag,
        "vault_http_status": after.get("http_status"),
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
