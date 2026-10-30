"""Generic alert webhook transport tests."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import Settings
from app.services.event_risk.alerts import emit_ops_alert, emit_quality_gate_alert


@pytest.mark.asyncio
async def test_emit_ops_alert_uses_webhook_when_configured():
    settings = Settings(
        ALERT_WEBHOOK_URL="https://hooks.example.com/alert",
        TELEGRAM_BOT_TOKEN="",
        TELEGRAM_CHAT_ID="",
    )
    with patch("app.services.event_risk.alerts.httpx.AsyncClient") as mock_client:
        instance = mock_client.return_value.__aenter__.return_value
        instance.post = AsyncMock(return_value=AsyncMock(status_code=200, raise_for_status=lambda: None))
        await emit_ops_alert(event="test_event", message="hello", settings=settings)
        instance.post.assert_called_once()
        assert "hooks.example.com" in instance.post.call_args[0][0]


@pytest.mark.asyncio
async def test_quality_gate_alert_reuses_webhook():
    settings = Settings(ALERT_WEBHOOK_URL="https://hooks.example.com/qg")
    with patch("app.services.event_risk.alerts.emit_ops_alert", new=AsyncMock()) as mock_emit:
        await emit_quality_gate_alert(source_id="cbr", failure_count=5, settings=settings)
        mock_emit.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_telegram_message_no_token():
    from app.services.alerts.telegram import send_telegram_message

    ok = await send_telegram_message("", "hello")
    assert ok is False
