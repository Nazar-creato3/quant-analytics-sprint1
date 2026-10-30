"""Tests for paginated admissions list."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.admissions import AdmissionCaseORM, AdmissionStatus
from app.services.admissions.service import admissions_service


def _case(idx: int, status: str) -> AdmissionCaseORM:
    return AdmissionCaseORM(
        id=f"case-{idx}",
        status=status,
        source="demo",
        contact_email=f"lead{idx}@test.com",
        contact_name=f"Lead {idx}",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_list_cases_paginated_filters_by_status():
    rows = [
        _case(1, AdmissionStatus.APPROVED.value),
        _case(2, AdmissionStatus.REJECTED.value),
        _case(3, AdmissionStatus.APPROVED.value),
    ]
    db = AsyncMock()

    async def fake_execute(stmt):
        result = MagicMock()
        sql = str(stmt)
        if "count" in sql.lower():
            result.scalar_one.return_value = 2
            return result
        result.scalars.return_value.all.return_value = [rows[0], rows[2]]
        return result

    db.execute = AsyncMock(side_effect=fake_execute)

    items, total = await admissions_service.list_cases_paginated(
        db,
        status=AdmissionStatus.APPROVED.value,
        sort="created_at_desc",
        page=1,
        page_size=10,
    )

    assert total == 2
    assert len(items) == 2
    assert all(c.status == AdmissionStatus.APPROVED.value for c in items)


@pytest.mark.asyncio
async def test_seed_demo_cases_skips_existing_email():
    db = AsyncMock()
    existing = _case(1, AdmissionStatus.LEAD.value)

    with patch.object(
        admissions_service,
        "find_latest_case_by_email",
        new=AsyncMock(side_effect=[existing, None, None]),
    ):
        created = await admissions_service.seed_demo_cases(db, count=3)

    assert created == 2
    assert db.add.call_count == 2
