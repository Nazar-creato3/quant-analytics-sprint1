"""Tests for Twenty CRM integration (mocked HTTP — no live API)."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.application_flow import ApplicationORM, ApplicationStatus
from app.services.crm.sync import sync_application_to_twenty
from app.services.crm.twenty import (
    CrmSyncStatus,
    TwentyCrmClient,
    TwentyCrmError,
    _extract_id,
    _split_name,
)


def _sample_app(**overrides) -> ApplicationORM:
    base = dict(
        id="app-test-1",
        name="Jane Doe",
        email="jane@example.com",
        phone="+79991234567",
        phone_hash="abc",
        status=ApplicationStatus.PENDING_VERIFICATION.value,
        duplicate_flag=False,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    base.update(overrides)
    return ApplicationORM(**base)


def test_split_name():
    assert _split_name("Jane Doe") == ("Jane", "Doe")
    assert _split_name("Cher") == ("Cher", "")
    assert _split_name(None) == ("Applicant", "")


def test_extract_id_variants():
    assert _extract_id({"data": {"id": "uuid-1"}}) == "uuid-1"
    assert _extract_id({"id": "uuid-2"}) == "uuid-2"
    assert _extract_id({"record": {"id": "uuid-3"}}) == "uuid-3"
    assert _extract_id({}) is None


def test_twenty_client_not_configured():
    client = TwentyCrmClient(api_url="", api_key="")
    assert client.configured is False


@pytest.mark.asyncio
async def test_sync_skipped_when_not_configured():
    db = AsyncMock()
    app = _sample_app()
    client = TwentyCrmClient(api_url="", api_key="")

    with patch("app.services.crm.sync.audit.log", new=AsyncMock()) as mock_audit:
        result = await sync_application_to_twenty(db, app, event="submitted", client=client)

    assert result["skipped"] is True
    assert app.crm_sync_status == CrmSyncStatus.SKIPPED.value
    mock_audit.assert_awaited_once()


@pytest.mark.asyncio
async def test_sync_creates_person_and_company():
    db = AsyncMock()
    app = _sample_app()
    client = TwentyCrmClient(api_url="https://crm.example.com", api_key="test-key")

    with (
        patch.object(client, "sync_application", new=AsyncMock(return_value={
            "person_id": "person-uuid",
            "company_id": "company-uuid",
        })),
        patch("app.services.crm.sync.audit.log", new=AsyncMock()),
    ):
        result = await sync_application_to_twenty(db, app, event="submitted", client=client)

    assert result["ok"] is True
    assert app.twenty_crm_id == "person-uuid"
    assert app.twenty_company_id == "company-uuid"
    assert app.crm_sync_status == CrmSyncStatus.SYNCED.value


@pytest.mark.asyncio
async def test_sync_idempotent_update():
    db = AsyncMock()
    app = _sample_app(
        twenty_crm_id="existing-person",
        twenty_company_id="existing-company",
        status=ApplicationStatus.PENDING_REVIEW.value,
    )
    client = TwentyCrmClient(api_url="https://crm.example.com", api_key="test-key")

    mock_sync = AsyncMock(return_value={
        "person_id": "existing-person",
        "company_id": "existing-company",
    })
    with (
        patch.object(client, "sync_application", mock_sync),
        patch("app.services.crm.sync.audit.log", new=AsyncMock()),
    ):
        await sync_application_to_twenty(db, app, event="email_verified", client=client)

    mock_sync.assert_awaited_once()
    call_app = mock_sync.await_args.kwargs.get("event") or mock_sync.await_args[1].get("event")
    assert call_app == "email_verified"


@pytest.mark.asyncio
async def test_sync_failure_sets_failed_status():
    db = AsyncMock()
    app = _sample_app()
    client = TwentyCrmClient(api_url="https://crm.example.com", api_key="test-key")

    with (
        patch.object(
            client,
            "sync_application",
            new=AsyncMock(side_effect=TwentyCrmError("boom", retryable=True)),
        ),
        patch("app.services.crm.sync.audit.log", new=AsyncMock()),
        pytest.raises(TwentyCrmError),
    ):
        await sync_application_to_twenty(db, app, event="submitted", client=client)

    assert app.crm_sync_status == CrmSyncStatus.FAILED.value


@pytest.mark.asyncio
async def test_twenty_health_check_ok():
    client = TwentyCrmClient(api_url="https://crm.example.com", api_key="test-key")
    with patch.object(client, "_request", new=AsyncMock(return_value={"data": []})):
        payload = await client.health_check()
    assert payload["ok"] is True
    assert payload["configured"] is True


@pytest.mark.asyncio
async def test_schedule_crm_sync_enqueues_task():
    from app.services.crm.sync import schedule_application_crm_sync

    mock_task = MagicMock()
    with patch("app.tasks.crm_sync.sync_application_to_twenty_task", mock_task):
        schedule_application_crm_sync("app-1", "submitted")
    mock_task.delay.assert_called_once_with("app-1", "submitted")
