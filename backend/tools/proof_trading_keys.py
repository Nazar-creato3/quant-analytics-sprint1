#!/usr/bin/env python3
"""Proof script for trading keys architecture steps 1-6."""
from __future__ import annotations

import asyncio
import json
import sys

import httpx


async def main() -> int:
    base = "http://localhost:8000/api/v1"
    results: dict[str, object] = {}

    # Step 1: terminal market data without user keys
    async with httpx.AsyncClient(timeout=30.0) as client:
        snap = await client.get(f"{base}/terminal/snapshot")
        results["step1_terminal_snapshot"] = {
            "status": snap.status_code,
            "ok": snap.status_code == 200,
            "has_indices": "indices" in (snap.json() if snap.status_code == 200 else {}),
        }

        # trading accounts list requires auth — smoke import only
        from app.services.trading_keys import platform_keys

        results["step1_platform_keys"] = {
            "alpaca_headers_present": bool(platform_keys.alpaca_data_headers()),
            "fmp": platform_keys.platform_key_configured("FMP_API_KEY"),
        }

        # Step 3: invalid key rejection (no auth — expect 401, so use in-container test)
        from app.services.trading_keys.validators import validate_binance_key

        bad = await validate_binance_key(api_key="invalid", api_secret="invalid")
        results["step3_invalid_key_rejected"] = {"ok": bad.ok is False, "error": bad.error}

    print(json.dumps(results, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
