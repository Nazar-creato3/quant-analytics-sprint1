#!/bin/sh
set -eu
export VAULT_ADDR=http://127.0.0.1:8200
ROOT=$(grep root_token /vault/data/.apex_init.json | head -1 | sed 's/.*"root_token"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/' | tr -d ' ,')
export VAULT_TOKEN="$ROOT"
vault kv put secret/apex-intel/trading probe=ok
vault kv get secret/apex-intel/trading
echo probe_write_ok
