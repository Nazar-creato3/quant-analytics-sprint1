#!/bin/sh
set -eu

export VAULT_ADDR="${VAULT_ADDR:-http://127.0.0.1:8200}"
INIT_FILE="/vault/data/.apex_init.json"
POLICY_NAME="apex-intel-trading-read"
TOKEN_FILE="/vault/data/.apex_backend_token"

json_field() {
  file="$1"
  field="$2"
  sed -n "s/.*\"${field}\":\"\([^\"]*\)\".*/\1/p" "$file" | head -n1
}

json_array_first() {
  file="$1"
  field="$2"
  sed -n "s/.*\"${field}\":\[\"\([^\"]*\)\".*/\1/p" "$file" | head -n1
}

vault server -config=/vault/config/config.hcl &
VAULT_PID=$!

sleep 2

# `vault status` exits 0 = unsealed, 2 = sealed or not initialized (server is up), 1 = unreachable.
vault_up() {
  rc=0
  vault status -address="$VAULT_ADDR" >/dev/null 2>&1 || rc=$?
  [ "$rc" -ne 1 ]
}

for _ in $(seq 1 30); do
  if vault_up; then
    break
  fi
  sleep 1
done

if ! vault_up; then
  echo "vault failed to start" >&2
  exit 1
fi

if vault status -address="$VAULT_ADDR" | grep -q "Initialized.*false"; then
  vault operator init -address="$VAULT_ADDR" -key-shares=1 -key-threshold=1 -format=json > "$INIT_FILE"
  chmod 600 "$INIT_FILE"
fi

if [ ! -f "$INIT_FILE" ]; then
  echo "missing init file at $INIT_FILE" >&2
  exit 1
fi

UNSEAL_KEY="$(grep -A1 unseal_keys_b64 "$INIT_FILE" | tail -1 | sed 's/.*"\([^"]*\)".*/\1/' | tr -d ' ,')"
ROOT_TOKEN="$(grep root_token "$INIT_FILE" | head -1 | sed 's/.*"\([^"]*\)".*/\1/' | tr -d ' ,')"

if [ -z "$UNSEAL_KEY" ] || [ -z "$ROOT_TOKEN" ]; then
  echo "failed to parse init json" >&2
  exit 1
fi

if vault status -address="$VAULT_ADDR" | grep -q "Sealed.*true"; then
  vault operator unseal -address="$VAULT_ADDR" "$UNSEAL_KEY" >/dev/null
fi

export VAULT_TOKEN="$ROOT_TOKEN"

if ! vault secrets list -address="$VAULT_ADDR" 2>/dev/null | grep -q "^secret/"; then
  vault secrets enable -address="$VAULT_ADDR" -path=secret kv-v2
fi

vault policy write -address="$VAULT_ADDR" "$POLICY_NAME" - <<'POLICY'
path "secret/data/apex-intel/trading" {
  capabilities = ["create", "read", "update"]
}
path "secret/data/apex-intel/trading/*" {
  capabilities = ["create", "read", "update"]
}
POLICY

if [ ! -f "$TOKEN_FILE" ]; then
  vault token create -address="$VAULT_ADDR" -policy="$POLICY_NAME" -ttl=8760h -format=json > "$TOKEN_FILE"
  chmod 600 "$TOKEN_FILE"
fi

wait "$VAULT_PID"
