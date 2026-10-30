"""Daily price history on disk, shared by API workers and Celery.

One JSON file per instrument under ``PRICE_HISTORY_DIR`` (default
``/app/data/price_history`` — the bind-mounted ./data on the server)::

    {"source": "moex_iss", "engine": "stock", "market": "shares", "board": "TQBR",
     "ccy": "RUB", "synced_at": "...", "bars": [["2026-10-23", 300.1, 3.7e9, 12345678.0], ...]}

Bar = [session_date, close, traded_value_in_ccy_or_null, volume_or_null], oldest first.
Bond closes are already in roubles per bond (ISS gives % of face value).

Readers keep an in-process cache keyed by file mtime, so hot paths
(risk engine, what-if) do not re-read JSON on every call.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from threading import Lock
from typing import Any

_lock = Lock()
_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def enabled() -> bool:
    """On in production/staging (or PRICE_HISTORY=1); off in tests unless asked."""
    flag = os.environ.get("PRICE_HISTORY", "").strip().lower()
    if flag in {"0", "false", "no"}:
        return False
    if flag in {"1", "true", "yes"}:
        return True
    return os.environ.get("APP_ENV", "").strip().lower() in {"production", "staging"}


def root() -> Path:
    env = os.environ.get("PRICE_HISTORY_DIR", "").strip()
    candidates = [Path(env)] if env else []
    candidates += [Path("/app/data/price_history"), Path(__file__).resolve().parents[3] / "data" / "price_history"]
    for cand in candidates:
        try:
            cand.mkdir(parents=True, exist_ok=True)
            probe = cand / ".probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return cand
        except OSError:
            continue
    fallback = Path(tempfile.gettempdir()) / "qa-price-history"
    fallback.mkdir(parents=True, exist_ok=True)
    # Temp dir dies with the container: say so loudly instead of silently losing history.
    import logging

    logging.getLogger(__name__).warning(
        "price_history store is not writable, using temp dir %s (lost on restart): fix permissions of %s",
        fallback,
        candidates[0] if candidates else "/app/data/price_history",
    )
    return fallback


def _path(ticker: str) -> Path:
    safe = ticker.upper().replace("/", "_").replace(" ", "_")
    return root() / f"{safe}.json"


def read(ticker: str) -> dict[str, Any] | None:
    path = _path(ticker)
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        return None
    key = ticker.upper()
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] == mtime:
            return hit[1]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    with _lock:
        _cache[key] = (mtime, payload)
    return payload


def write(ticker: str, payload: dict[str, Any]) -> None:
    from datetime import datetime, timezone

    payload = {"ticker": ticker.upper(), "synced_at": datetime.now(timezone.utc).isoformat(), **payload}
    path = _path(ticker)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)
    with _lock:
        _cache.pop(ticker.upper(), None)


def known() -> list[str]:
    try:
        return sorted(p.stem for p in root().glob("*.json"))
    except OSError:
        return []


def clear_cache() -> None:
    with _lock:
        _cache.clear()
