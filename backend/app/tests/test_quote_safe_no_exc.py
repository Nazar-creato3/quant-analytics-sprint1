"""GA16-312: quote failures must not leak exception text to the client."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.terminal_platform.market.quotes import fetch_quote_safe


@pytest.mark.asyncio
async def test_quote_exception_hides_exception_text() -> None:
    router = SimpleNamespace(get_quote=AsyncMock(side_effect=RuntimeError("secret host leaked")))
    with patch(
        "app.services.terminal_platform.market.quotes.get_terminal_router",
        return_value=router,
    ):
        body = await fetch_quote_safe("SBER")
    assert body["status"] == "no_data"
    assert body["reason"] == "нет данных"
    assert "secret" not in str(body).lower()
    assert "leaked" not in str(body).lower()
