from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.application.turnstile import _public_remote_ip, verify_turnstile


def test_public_remote_ip_drops_private_and_keeps_global():
    assert _public_remote_ip("10.0.0.8") is None
    assert _public_remote_ip("172.18.0.4") is None
    assert _public_remote_ip("127.0.0.1") is None
    assert _public_remote_ip("::1") is None
    assert _public_remote_ip("8.8.8.8") == "8.8.8.8"


@pytest.mark.asyncio
async def test_verify_skips_when_secret_missing():
    with patch("app.services.application.turnstile.settings") as mock_settings:
        mock_settings.TURNSTILE_SECRET_KEY = ""
        assert await verify_turnstile("anything") is True
        assert await verify_turnstile("") is True


@pytest.mark.asyncio
async def test_verify_does_not_send_private_remoteip():
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"success": True}
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("app.services.application.turnstile.settings") as mock_settings,
        patch("app.services.application.turnstile.httpx.AsyncClient", return_value=mock_client),
    ):
        mock_settings.TURNSTILE_SECRET_KEY = "secret"
        ok = await verify_turnstile("tok", remote_ip="172.18.0.4")
    assert ok is True
    sent = mock_client.post.await_args.kwargs["data"]
    assert "remoteip" not in sent
    assert sent["response"] == "tok"
