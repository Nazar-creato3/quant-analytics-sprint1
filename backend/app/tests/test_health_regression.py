"""Hourly regression tests for the 3 known production bugs (Prompt 1)."""
from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime, timezone

import httpx
import pytest
import websockets

BASE_URL = os.environ.get("HEALTH_CHECK_BASE_URL", "https://quantanalyticsclub.ru").rstrip("/")
WS_URL = os.environ.get(
    "HEALTH_CHECK_WS_URL",
    BASE_URL.replace("https://", "wss://").replace("http://", "ws://") + "/api/v1/ws/terminal",
)
CHAT_TOKEN = os.environ.get("HEALTH_CHECK_CHAT_TOKEN") or os.environ.get("TEST_USER_A_TOKEN", "")
DEBUG_LEAK_RE = re.compile(r"confidence\s*\d+%.*horizon", re.IGNORECASE | re.DOTALL)


def _parse_ts(raw: str | None) -> datetime:
    if not raw:
        raise AssertionError("missing timestamp in response")
    text = raw.replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def test_spy_gspc_correlation_invariant():
    """Known invariant: SPY vs ^GSPC must correlate > 0.9 on aligned dates."""
    from app.services.forecast.global_macro_view import (
        _align_dated_returns,
        _compute_correlation_matrix,
        _returns_from_dated_closes,
    )

    base = 400.0
    dated_spy: dict[str, float] = {}
    dated_gspc: dict[str, float] = {}
    for i in range(60):
        date = f"2024-01-{i + 1:02d}" if i < 31 else f"2024-02-{i - 30:02d}"
        if i >= 59:
            date = "2024-02-28"
        move = 0.001 * (1 if i % 3 else -1)
        base *= 1.0 + move
        dated_spy[date] = base
        dated_gspc[date] = base * 1.0001

    aligned = _align_dated_returns(
        {
            "SPY": _returns_from_dated_closes(dated_spy),
            "^GSPC": _returns_from_dated_closes(dated_gspc),
        }
    )
    matrix, _symbols = _compute_correlation_matrix(aligned)
    corr = matrix["SPY"]["^GSPC"]
    assert corr > 0.9, f"SPY/^GSPC correlation {corr} expected > 0.9"


def test_market_data_freshness():
    with httpx.Client(timeout=30.0) as client:
        r = client.get(f"{BASE_URL}/api/market/indices")
        r.raise_for_status()
        body = r.json()
    freshness_ts = body.get("fetched_at") or body.get("last_updated") or body.get("as_of")
    age = (datetime.now(timezone.utc) - _parse_ts(freshness_ts)).total_seconds()
    indices = body.get("indices") or []
    ok_rows = [i for i in indices if (i or {}).get("status") == "ok" and (i or {}).get("price")]
    assert ok_rows, "no index prices returned"
    assert age < 120, f"indices fetch stale by {age:.0f}s (fetched_at={freshness_ts})"


def test_no_cross_user_position_leak():
    token_a = os.environ.get("TEST_USER_A_TOKEN", "").strip()
    token_b = os.environ.get("TEST_USER_B_TOKEN", "").strip()
    if not token_a or not token_b:
        pytest.skip("TEST_USER_A_TOKEN and TEST_USER_B_TOKEN required")
    params = {"status": "approved,filled,executing", "page_size": 100}

    def _ids(token: str) -> set[str]:
        headers = {"Authorization": f"Bearer {token}"}
        with httpx.Client(timeout=60.0) as client:
            r = client.get(f"{BASE_URL}/api/positions", headers=headers, params=params)
            r.raise_for_status()
            items = r.json().get("items") or []
        return {str(m.get("id")) for m in items if m.get("id")}

    ids_a = _ids(token_a)
    ids_b = _ids(token_b)
    overlap = ids_a & ids_b
    assert not overlap, f"position IDs shared across users: {overlap}"


def test_chat_no_raw_debug_output():
    enabled = os.environ.get("HEALTH_LIVE_CHAT_CHECK_ENABLED", "false").lower() in {
        "1",
        "true",
        "yes",
    }
    if not enabled:
        pytest.skip("live chat health check disabled (HEALTH_LIVE_CHAT_CHECK_ENABLED=false)")
    token = CHAT_TOKEN.strip()
    if not token:
        pytest.skip("HEALTH_CHECK_CHAT_TOKEN or TEST_USER_A_TOKEN required")
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"message": "почему такой score по SBER?"}
    with httpx.Client(timeout=240.0) as client:
        r = client.post(f"{BASE_URL}/api/chat", headers=headers, json=payload)
        r.raise_for_status()
        body = r.json()
    text = body.get("response") or (body.get("advisor_message") or {}).get("body") or json.dumps(body)
    assert not DEBUG_LEAK_RE.search(text), "raw debug verdict leaked in chat response"
    assert "не инвестиционная рекомендация" in text.lower() or "не инвестиционная рекомендация" in text


def test_news_feed_freshness():
    """News feed must expose freshness metadata and not be stale (>1h since refresh)."""
    with httpx.Client(timeout=45.0) as client:
        r = client.get(f"{BASE_URL}/api/v1/terminal/news", params={"limit": 8})
        r.raise_for_status()
        body = r.json()
    meta = (body.get("metadata") or {}).get("freshness") or {}
    last_refreshed = meta.get("last_refreshed_at")
    assert last_refreshed, "missing last_refreshed_at in /terminal/news metadata.freshness"
    age = (datetime.now(timezone.utc) - _parse_ts(last_refreshed)).total_seconds()
    stale_after = float(meta.get("stale_after_sec") or 3600)
    items = body.get("data") or []
    assert items, "news feed returned no headlines"
    assert not meta.get("is_stale"), f"news feed marked stale (age={age:.0f}s, last={last_refreshed})"
    assert age < stale_after, f"news feed stale by {age:.0f}s (last_refreshed_at={last_refreshed})"


@pytest.mark.slow
def test_websocket_delivers_message():
    async def _wait_for_message() -> dict:
        async with websockets.connect(WS_URL, open_timeout=15, close_timeout=5) as ws:
            deadline = asyncio.get_event_loop().time() + 15
            while asyncio.get_event_loop().time() < deadline:
                raw = await asyncio.wait_for(ws.recv(), timeout=15)
                msg = json.loads(raw)
                if msg.get("type") in ("tick", "connected", "heartbeat"):
                    return msg
        raise AssertionError("no websocket message within 15 seconds")

    msg = asyncio.run(_wait_for_message())
    assert msg.get("type") in ("tick", "connected", "heartbeat")
