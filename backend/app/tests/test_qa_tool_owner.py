"""GA16-304: qa_* tools must not fall back to demo without an owner."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.services.chat.tools import execute_tool


@pytest.mark.asyncio
async def test_qa_tool_without_owner_does_not_use_demo() -> None:
    with patch("app.services.chat.qa_registry.invoke") as invoke:
        raw = await execute_tool(AsyncMock(), "qa_portfolio_report", {})
    body = json.loads(raw)
    assert body["data_available"] is False
    assert body["error"] == "owner_required"
    invoke.assert_not_called()


@pytest.mark.asyncio
async def test_qa_tool_with_owner_passes_user_id() -> None:
    with patch("app.services.chat.qa_registry.invoke", return_value={"ok": True}) as invoke:
        raw = await execute_tool(
            AsyncMock(),
            "qa_portfolio_report",
            {"ticker": "SBER"},
            owner_user_id="user-42",
        )
    assert json.loads(raw) == {"ok": True}
    invoke.assert_called_once_with(name="qa_portfolio_report", user_id="user-42", ticker="SBER")
