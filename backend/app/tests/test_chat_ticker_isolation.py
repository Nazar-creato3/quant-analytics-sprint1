"""Tests for per-ticker chat conversation isolation."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.chat import ConversationCreate, ConversationORM, ConversationStatus
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


def test_normalize_symbol():
    assert chat_service._normalize_symbol(" amzn ") == "AMZN"
    assert chat_service._normalize_symbol("") is None
    assert chat_service._normalize_symbol(None) is None


@pytest.mark.asyncio
async def test_find_open_conversation_for_symbol_scopes_by_user_and_symbol():
    amzn_conv = _conv(id="conv-amzn", related_symbol="AMZN")
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = amzn_conv
    db.execute = AsyncMock(return_value=result)

    found = await chat_service._find_open_conversation_for_symbol(
        db,
        client_profile_id="user-1",
        symbol="amzn",
    )

    assert found is amzn_conv
    db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_conversation_reuses_existing_symbol_thread():
    existing = _conv(id="conv-amzn", related_symbol="AMZN")
    db = AsyncMock()
    with patch.object(
        chat_service,
        "_find_open_conversation_for_symbol",
        new=AsyncMock(return_value=existing),
    ):
        conv = await chat_service.create_conversation(
            db,
            client_profile_id="user-1",
            body=ConversationCreate(related_symbol="AMZN"),
            identity=None,
            user_id="user-1",
            system_role=SystemRole.USER,
        )

    assert conv.id == "conv-amzn"
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_list_conversations_filters_by_related_symbol():
    amzn = _conv(id="conv-amzn", related_symbol="AMZN")
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [amzn]
    db.execute = AsyncMock(return_value=result)

    items = await chat_service.list_conversations(
        db,
        identity=None,
        user_id="user-1",
        system_role=SystemRole.USER,
        related_symbol="amzn",
    )

    assert len(items) == 1
    assert items[0].related_symbol == "AMZN"
