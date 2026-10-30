#!/usr/bin/env bash
# One-time Vault enablement on VPS (run from repo root on quant-vps).
set -euo pipefail

APP_DIR="${APP_DIR:-$HOME/myapp}"
cd "$APP_DIR"

echo "Starting Vault..."
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d vault

echo "Waiting for Vault health..."
for i in $(seq 1 30); do
  if docker exec apex-vault vault status -address=http://127.0.0.1:8200 >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

if docker exec apex-vault vault status -address=http://127.0.0.1:8200 | grep -q "Sealed.*true"; then
  echo "Unsealing Vault..."
  docker cp ~/myapp/infrastructure/vault/manual_init.sh apex-vault:/tmp/manual_init.sh 2>/dev/null || true
  docker exec apex-vault sh -c '
    export VAULT_ADDR=http://127.0.0.1:8200
    UNSEAL=$(grep -A1 unseal_keys_b64 /vault/data/.apex_init.json | tail -1 | sed "s/.*\"\([^\"]*\)\".*/\1/" | tr -d " ,")
    vault operator unseal "$UNSEAL" >/dev/null
  '
fi

docker exec apex-vault vault status -address=http://127.0.0.1:8200

TOKEN_JSON="$(docker exec apex-vault cat /vault/data/.apex_backend_token 2>/dev/null || true)"
if [ -z "$TOKEN_JSON" ]; then
  echo "Backend token file missing — check apex-vault logs" >&2
  exit 1
fi

CLIENT_TOKEN="$(sed -n 's/.*"client_token":"\([^"]*\)".*/\1/p' <<<"$TOKEN_JSON" | head -n1)"
if [ -z "$CLIENT_TOKEN" ]; then
  CLIENT_TOKEN="$(sed -n 's/.*"client_token":"\([^"]*\)".*/\1/p' /tmp/vault_token.json 2>/dev/null | head -n1)"
fi

if [ -z "$CLIENT_TOKEN" ]; then
  echo "Could not parse client_token from .apex_backend_token" >&2
  exit 1
fi

if grep -q '^SECRETS_BACKEND=' .env 2>/dev/null; then
  sed -i 's/^SECRETS_BACKEND=.*/SECRETS_BACKEND=vault/' .env
else
  echo 'SECRETS_BACKEND=vault' >> .env
fi

if grep -q '^VAULT_ADDR=' .env 2>/dev/null; then
  sed -i 's|^VAULT_ADDR=.*|VAULT_ADDR=http://vault:8200|' .env
else
  echo 'VAULT_ADDR=http://vault:8200' >> .env
fi

if grep -q '^VAULT_TOKEN=' .env 2>/dev/null; then
  sed -i "s|^VAULT_TOKEN=.*|VAULT_TOKEN=${CLIENT_TOKEN}|" .env
else
  echo "VAULT_TOKEN=${CLIENT_TOKEN}" >> .env
fi

if ! grep -q '^VAULT_SECRET_PATH=' .env 2>/dev/null; then
  echo 'VAULT_SECRET_PATH=secret/data/apex-intel/trading' >> .env
fi

echo "Recreating backend + workers with SECRETS_BACKEND=vault..."
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --no-deps backend celery-pipeline celery-beat celery-execution

echo "Migrating trading keys from env into Vault (one-time)..."
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T backend python scripts/migrate_trading_secrets_to_vault.py || true

echo "Health check (names only, no secret values):"
curl -sf "http://127.0.0.1:8000/api/v1/health" | python3 -m json.tool || curl -sf "https://quantanalyticsclub.ru/api/v1/health" | python3 -m json.tool

echo "Done. Remove BINANCE_*, TINKOFF_*, FINAM_* from .env after verifying vault_keys_present."
