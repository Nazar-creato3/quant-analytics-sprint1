#!/bin/sh
set -eu
export VAULT_ADDR=http://127.0.0.1:8200

if vault status | grep -q "Initialized.*false"; then
  vault operator init -key-shares=1 -key-threshold=1 -format=json > /vault/data/.apex_init.json
  chmod 600 /vault/data/.apex_init.json
fi

UNSEAL=$(grep -A1 unseal_keys_b64 /vault/data/.apex_init.json | tail -1 | sed 's/.*"\([^"]*\)".*/\1/' | tr -d ' ,')
ROOT=$(grep root_token /vault/data/.apex_init.json | head -1 | sed 's/.*"\([^"]*\)".*/\1/' | tr -d ' ,')
if [ -z "$UNSEAL" ] || [ -z "$ROOT" ]; then
  echo "parse init json failed" >&2
  exit 1
fi
vault operator unseal "$UNSEAL" >/dev/null
export VAULT_TOKEN="$ROOT"
vault secrets enable -path=secret kv-v2 2>/dev/null || true
vault policy write apex-intel-trading-read - <<'POL'
path "secret/data/apex-intel/trading" {
  capabilities = ["create", "read", "update"]
}
POL
vault token create -policy=apex-intel-trading-read -ttl=8760h -format=json > /vault/data/.apex_backend_token
chmod 600 /vault/data/.apex_backend_token
vault status
