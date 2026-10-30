"""Tests for expensive health check throttling."""
from __future__ import annotations

import pytest

from app.services.health.expensive_check_throttle import run_throttled_expensive_check


@pytest.mark.asyncio
async def test_expensive_check_disabled_skips_runner(monkeypatch):
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "HEALTH_LIVE_CHAT_CHECK_ENABLED", False)

    called = False

    async def runner(_settings):
        nonlocal called
        called = True
        return {"status": "passed"}

    row = await run_throttled_expensive_check(
        "chat_no_raw_debug",
        runner,
        settings=settings,
        enabled_attr="HEALTH_LIVE_CHAT_CHECK_ENABLED",
        interval_attr="HEALTH_LIVE_CHAT_INTERVAL_SECONDS",
    )
    assert called is False
    assert row.get("skipped") == "live_disabled"
    assert row.get("status") == "passed"
