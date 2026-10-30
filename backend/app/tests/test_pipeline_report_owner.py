"""Pipeline report owner resolution and per-user isolation tests."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.models import User, UserRole
from app.tasks.pipeline import _resolve_report_owner_id


def _user(user_id: str = "user-1", email: str = "alice@test.com", role: UserRole = UserRole.VIEWER) -> User:
    return User(
        id=user_id,
        email=email,
        hashed_password="x",
        role=role,
        is_active=True,
        is_whitelisted=True,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _admin_user(user_id: str = "admin-1", email: str = "admin@test.com") -> User:
    return _user(user_id=user_id, email=email, role=UserRole.ADMIN)


@pytest.mark.asyncio
async def test_resolve_owner_from_trigger_email():
    alice = _user()
    session = AsyncMock()
    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = alice
    session.execute = AsyncMock(return_value=user_result)

    owner_id = await _resolve_report_owner_id(session, "ops:alice@test.com")
    assert owner_id == alice.id


@pytest.mark.asyncio
async def test_resolve_owner_from_user_id_prefix():
    bob = _user(user_id="user-b", email="bob@test.com")
    session = AsyncMock()
    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = bob
    session.execute = AsyncMock(return_value=user_result)

    owner_id = await _resolve_report_owner_id(session, "beat:user:user-b")
    assert owner_id == bob.id


@pytest.mark.asyncio
async def test_beat_scheduled_does_not_use_pipeline_owner_email(monkeypatch):
    from app.core.config import settings

    admin = _admin_user(email="pipeline-owner@test.com")
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
        ]
    )

    monkeypatch.setattr(settings, "PIPELINE_OWNER_EMAIL", "pipeline-owner@test.com")

    owner_id = await _resolve_report_owner_id(session, "beat:scheduled")
    assert owner_id is None


@pytest.mark.asyncio
async def test_system_ops_may_use_pipeline_owner_email(monkeypatch):
    from app.core.config import settings

    admin = _admin_user(email="pipeline-owner@test.com")
    session = AsyncMock()
    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = admin
    session.execute = AsyncMock(return_value=user_result)

    monkeypatch.setattr(settings, "PIPELINE_OWNER_EMAIL", "pipeline-owner@test.com")

    owner_id = await _resolve_report_owner_id(session, "system:maintenance")
    assert owner_id == admin.id


@pytest.mark.asyncio
async def test_system_ops_falls_back_to_first_admin(monkeypatch):
    from app.core.config import settings

    admin = _admin_user()
    session = AsyncMock()

    admin_result = MagicMock()
    admin_result.scalar_one_or_none.return_value = admin
    session.execute = AsyncMock(return_value=admin_result)

    monkeypatch.setattr(settings, "PIPELINE_OWNER_EMAIL", "")

    owner_id = await _resolve_report_owner_id(session, "system:batch")
    assert owner_id == admin.id


def test_reports_for_user_scoped_by_created_by():
    from app.services.portfolio.user_scope import reports_for_user

    stmt = reports_for_user("user-a")
    compiled = str(stmt).lower()
    assert "created_by" in compiled
    assert "maneuver_reports" in compiled


def test_report_for_user_includes_report_id():
    from app.services.portfolio.user_scope import report_for_user

    stmt = report_for_user("user-a", "report-1")
    compiled = str(stmt).lower()
    assert "created_by" in compiled
    assert "report" in compiled


def test_pipeline_persist_binds_rls_user():
    """Pipeline celery task must set app.user_id before INSERT (0032_portfolio_rls)."""
    from pathlib import Path

    source = Path(__file__).resolve().parents[1] / "tasks" / "pipeline.py"
    text = source.read_text(encoding="utf-8")
    assert "set_session_user_id" in text
    idx_rls = text.index("set_session_user_id")
    idx_report = text.index("ManeuverReport(")
    assert idx_rls < idx_report


@pytest.mark.asyncio
async def test_scheduled_pipeline_dispatches_per_eligible_user():
    from app.tasks.pipeline import _async_scheduled_pipeline

    alice = _user(user_id="user-a", email="alice@test.com")
    bob = _user(user_id="user-b", email="bob@test.com")

    mock_session = AsyncMock()

    with patch(
        "app.services.pipeline.eligible_users.list_pipeline_eligible_users",
        new=AsyncMock(return_value=[alice, bob]),
    ), patch(
        "app.db.session.AsyncSessionLocal",
    ) as session_cls, patch(
        "app.services.settings.watchlist.get_effective_watchlist",
        new=AsyncMock(return_value=["SPY"]),
    ), patch(
        "app.services.portfolio.metrics._user_portfolio_size",
        new=AsyncMock(return_value=100_000.0),
    ), patch(
        "app.services.portfolio.metrics._user_confidence_threshold",
        new=AsyncMock(return_value=0.55),
    ), patch(
        "app.tasks.pipeline.run_pipeline_task.delay",
    ) as delay_mock, patch(
        "app.utils.pipeline_tracker.track_run",
    ):
        session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        session_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        delay_mock.return_value = MagicMock(id="task-1")

        result = await _async_scheduled_pipeline()

    assert result["status"] == "queued"
    assert result["user_count"] == 2
    assert delay_mock.call_count == 2
    for call in delay_mock.call_args_list:
        kwargs = call.kwargs
        assert kwargs["owner_user_id"] in {"user-a", "user-b"}
        assert kwargs["triggered_by"].startswith("beat:")
        assert "@" in kwargs["triggered_by"]
