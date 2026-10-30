"""Supabase insert helpers for crypto_data (service/collector use)."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any


def _client():
    from supabase import create_client

    url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    # Prefer service_role/secret for inserts (bypasses RLS); publishable for reads if no secret.
    key = (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or os.getenv("SUPABASE_SECRET_KEY")
        or os.getenv("SUPABASE_KEY")
        or os.getenv("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY")
    )
    if not url or not key:
        raise RuntimeError(
            "Supabase URL/key missing. Set SUPABASE_URL and SUPABASE_KEY "
            "(or NEXT_PUBLIC_SUPABASE_* for publishable-only reads)."
        )
    return create_client(url, key)


def insert_crypto_row(
    symbol: str,
    price: float | None = None,
    volume_24h: float | None = None,
    open_interest: float | None = None,
    funding_rate: float | None = None,
) -> dict[str, Any]:
    """Insert one row into public.crypto_data."""
    client = _client()
    payload = {
        "symbol": symbol,
        "price": price,
        "volume_24h": volume_24h,
        "open_interest": open_interest,
        "funding_rate": funding_rate,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    result = client.table("crypto_data").insert(payload).execute()
    return {"ok": True, "data": result.data}


def fetch_recent(limit: int = 50) -> dict[str, Any]:
    """Read recent crypto_data rows (publishable key may be RLS-limited)."""
    client = _client()
    result = (
        client.table("crypto_data")
        .select("*")
        .order("timestamp", desc=True)
        .limit(limit)
        .execute()
    )
    return {"ok": True, "count": len(result.data or []), "data": result.data or []}
