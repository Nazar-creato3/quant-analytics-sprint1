#!/usr/bin/env python3
"""Collect BTCUSDT ticker via CCXT and insert into Supabase crypto_data.

Usage (from repo root, with env loaded):
  backend\\.venv\\Scripts\\python.exe backend\\scripts\\collect_crypto_to_supabase.py

Required env:
  SUPABASE_URL or NEXT_PUBLIC_SUPABASE_URL
  Prefer SUPABASE_SERVICE_ROLE_KEY (or sb_secret_*) for inserts.
  Fallback: SUPABASE_KEY / NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY (needs INSERT RLS).

Note: publishable/anon inserts fail with 42501 unless an INSERT policy exists.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

# Load .env.local / .env if python-dotenv present (root .env.local first)
for env_name in (".env.local", ".env", "frontend/.env.local", "backend/.env"):
    env_path = ROOT / env_name
    if env_path.is_file():
        try:
            from dotenv import load_dotenv

            load_dotenv(env_path, override=False)
        except ImportError:
            break


def _prefer_service_role_for_inserts() -> None:
    """Ensure insert path uses service_role/secret when present; keep publishable for reads elsewhere."""
    service = (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or os.getenv("SUPABASE_SECRET_KEY")
        or ""
    ).strip()
    if service:
        # supabase_store._client reads SUPABASE_SERVICE_ROLE_KEY first
        os.environ["SUPABASE_SERVICE_ROLE_KEY"] = service
        key_kind = "service_role/secret"
    else:
        pub = (
            os.getenv("SUPABASE_KEY")
            or os.getenv("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY")
            or ""
        ).strip()
        key_kind = "publishable/anon" if pub else "MISSING"
    print(f"supabase insert key: {key_kind}")


def main() -> int:
    from app.services.crypto_stack.market import fetch_ticker
    from app.services.crypto_stack.supabase_store import insert_crypto_row

    _prefer_service_role_for_inserts()

    ticker = fetch_ticker("BTC/USDT")
    price = ticker.get("last")
    vol = ticker.get("quote_volume")
    print(f"ticker BTC/USDT last={price} quote_vol={vol}")

    result = insert_crypto_row(
        symbol="BTCUSDT",
        price=float(price) if price is not None else None,
        volume_24h=float(vol) if vol is not None else None,
    )
    print("supabase insert:", result)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
