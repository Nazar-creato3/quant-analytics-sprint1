#!/bin/bash
set -euo pipefail
echo "=== DNS ==="
getent hosts data.alpaca.markets api.polygon.io api.binance.com iss.moex.com query1.finance.yahoo.com || true
echo "=== CURL FROM HOST ==="
for pair in \
  "alpaca|https://data.alpaca.markets/v2" \
  "polygon|https://api.polygon.io/v2/aggs/ticker/AAPL/prev?adjusted=true" \
  "binance|https://api.binance.com/api/v3/ping" \
  "yahoo|https://query1.finance.yahoo.com/v8/finance/chart/AAPL" \
  "moex|https://iss.moex.com/iss/index.json"; do
  name="${pair%%|*}"
  url="${pair#*|}"
  code=$(curl -sS -o /tmp/curl_body.txt -w "%{http_code}" --connect-timeout 8 --max-time 12 "$url" 2>/tmp/curl_err.txt || echo "ERR")
  err=$(tr '\n' ' ' </tmp/curl_err.txt 2>/dev/null || true)
  echo "$name status=$code err=$err"
done
echo "=== CURL FROM BACKEND CONTAINER ==="
docker exec apex-backend python - <<'PY'
import asyncio, httpx, json
urls = [
  ("alpaca", "https://data.alpaca.markets/v2"),
  ("polygon", "https://api.polygon.io/v2/aggs/ticker/AAPL/prev?adjusted=true"),
  ("binance", "https://api.binance.com/api/v3/ping"),
  ("yahoo", "https://query1.finance.yahoo.com/v8/finance/chart/AAPL"),
  ("moex", "https://iss.moex.com/iss/index.json"),
]
async def main():
  async with httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=8.0)) as c:
    for name, url in urls:
      try:
        r = await c.get(url)
        print(json.dumps({"name": name, "status": r.status_code, "secs": None}))
      except Exception as e:
        print(json.dumps({"name": name, "error": f"{type(e).__name__}: {e}"}))
asyncio.run(main())
PY
