"""Workstream 3 tests: chat, RBAC, refresh tokens, admissions escalate, connector health."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.admissions import AdmissionStatus
from app.domain.chat import ConversationCreate, MessageCreate, MessageSenderRole
from app.domain.rbac import SystemRole, has_permission
from app.services.admissions.service import admissions_service
from app.services.chat.service import ChatAccessError, chat_service
from app.services.chat.ticker_advisor import default_ticker_title, extract_symbol_from_text
from app.services.signup_abuse.guard import score_signup_abuse


def test_operator_has_chat_and_ops_permissions():
    assert has_permission(SystemRole.OPERATOR_ADMIN, "chat.read")
    assert has_permission(SystemRole.OPERATOR_ADMIN, "chat.queue")
    assert has_permission(SystemRole.OPERATOR_ADMIN, "ops.read")
    assert has_permission(SystemRole.OPERATOR_ADMIN, "billing.manage")


def test_user_has_chat_but_not_ops():
    assert has_permission(SystemRole.USER, "chat.write")
    assert not has_permission(SystemRole.USER, "ops.read")


def test_signup_abuse_velocity_flag():
    r = score_signup_abuse(
        email="user@example.com",
        velocity_flag=True,
    )
    assert "velocity" in r.signals.details
    assert r.risk_score >= 0.3


def test_chat_sender_role_mapping():
    assert chat_service.sender_role_for(SystemRole.OWNER_ADMIN) == MessageSenderRole.OWNER_ADMIN
    assert chat_service.sender_role_for(SystemRole.USER) == MessageSenderRole.CLIENT


def test_extract_symbol_from_question():
    assert extract_symbol_from_text("AMZN, прогноз на неделю") == "AMZN"
    assert extract_symbol_from_text("hello world") is None


def test_default_ticker_title():
    assert default_ticker_title("amzn") == "AMZN · прогноз и анализ"


def test_title_from_question():
    assert chat_service._title_from_question("прогноз на неделю", "AMZN") == "AMZN, прогноз на неделю"


@pytest.mark.asyncio
async def test_chat_client_cannot_access_other_profile():
    db = AsyncMock()

    with patch.object(
        chat_service,
        "get_conversation",
        new=AsyncMock(side_effect=ChatAccessError("Conversation access denied")),
    ):
        with pytest.raises(ChatAccessError):
            await chat_service.send_message(
                db,
                "conv-1",
                identity=None,
                user_id="user-a",
                system_role=SystemRole.USER,
                body=MessageCreate(body="hello"),
            )


@pytest.mark.asyncio
async def test_escalate_case_performs_transition():
    db = AsyncMock()
    case = MagicMock()
    case.id = "case-1"
    case.status = AdmissionStatus.LEAD.value
    case.extra = {}

    with patch.object(admissions_service, "get_case", new=AsyncMock(return_value=case)):
        with patch.object(admissions_service, "change_status", new=AsyncMock(return_value=case)) as mock_change:
            with patch("app.services.admissions.service.audit.log", new=AsyncMock()):
                await admissions_service.escalate_case(db, "case-1", actor_user_id="admin-1")
    mock_change.assert_awaited_once()
    args = mock_change.await_args
    assert args.args[2] == AdmissionStatus.CONTACTED


@pytest.mark.asyncio
async def test_refresh_token_reuse_revokes_family():
    from app.core.security import rotate_refresh_token
    from app.domain.refresh_token import RefreshTokenFamilyORM

    family = RefreshTokenFamilyORM(
        id="fam-1",
        subject="u@example.com",
        current_jti="jti-current",
        revoked=False,
    )
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = family
    db.execute = AsyncMock(return_value=result)

    with pytest.raises(ValueError, match="reuse"):
        await rotate_refresh_token(
            db,
            subject="u@example.com",
            family_id="fam-1",
            presented_jti="old-jti",
        )
    assert family.revoked is True


def test_migration_has_messages_revoke():
    from pathlib import Path

    text = Path(__file__).resolve().parents[2].joinpath(
        "alembic", "versions", "0025_workstream3_chat_tokens.py"
    ).read_text(encoding="utf-8")
    assert "REVOKE UPDATE, DELETE ON chat_messages" in text


@pytest.mark.asyncio
async def test_connector_health_builds_rows():
    from app.services.ops.connector_health import build_connector_health

    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))
    with patch("app.services.ops.connector_health.cache_get", new=AsyncMock(return_value=None)):
        payload = await build_connector_health(db)
    assert payload["summary"]["total"] >= 8
    ids = {row["connector_id"] for row in payload["items"]}
    assert "binance" in ids
    assert "macro_adapters" in ids
