"""Tests for chat conversation archive (new chat reset)."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.chat import ConversationORM, ConversationStatus
from app.domain.rbac import SystemRole
from app.services.chat.service import chat_service


def _conv(**kwargs) -> ConversationORM:
    defaults = {
        "id": "conv-1",
        "client_profile_id": "user-1",
        "status": ConversationStatus.OPEN.value,
        "created_at": datetime.now(timezone.utc),
    }
    defaults.update(kwargs)
    return ConversationORM(**defaults)


@pytest.mark.asyncio
async def test_archive_conversation_sets_status_archived():
    conv = _conv(status=ConversationStatus.OPEN.value)
    db = AsyncMock()

    with patch.object(
        chat_service,
        "get_conversation",
        new=AsyncMock(return_value=conv),
    ):
        result = await chat_service.archive_conversation(
            db,
            "conv-1",
            identity=None,
            user_id="user-1",
            system_role=SystemRole.USER,
        )

    assert conv.status == ConversationStatus.ARCHIVED.value
    assert result.status == ConversationStatus.ARCHIVED.value
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_find_open_conversation_skips_archived():
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=result)

    found = await chat_service._find_open_conversation_for_symbol(
        db,
        client_profile_id="user-1",
        symbol="AMZN",
    )

    assert found is None
    db.execute.assert_awaited_once()
