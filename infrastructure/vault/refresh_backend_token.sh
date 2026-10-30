#!/bin/sh
set -eu
export VAULT_ADDR=http://127.0.0.1:8200
ROOT=$(grep root_token /vault/data/.apex_init.json | head -1 | sed 's/.*"root_token"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/' | tr -d ' ,')
export VAULT_TOKEN="$ROOT"
vault secrets list
vault policy read apex-intel-trading-read
vault token create -policy=apex-intel-trading-read -ttl=8760h -format=json > /vault/data/.apex_backend_token
chmod 600 /vault/data/.apex_backend_token
echo token_refreshed
