"""Unit tests for CustomBasketService — CRUD and active position integrity."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.custom_basket import (
    CustomBasketCreate,
    CustomBasketItemCreate,
    CustomBasketItemORM,
    CustomBasketORM,
    CustomBasketUpdate,
)
from app.domain.deal_intent_enums import DealIntentStatus
from app.domain.sleeve import SleeveORM
from app.services.custom_basket.service import (
    CustomBasketIntegrityError,
    CustomBasketNotFoundError,
    CustomBasketService,
    CustomBasketValidationError,
)


def _items(*pairs: tuple[int, str]) -> list[CustomBasketItemCreate]:
    return [
        CustomBasketItemCreate(instrument_id=instrument_id, weight_pct=Decimal(weight))
        for instrument_id, weight in pairs
    ]


def _basket_row(**overrides) -> CustomBasketORM:
    now = datetime(2026, 7, 18, tzinfo=timezone.utc)
    defaults = {
        "id": "basket-1",
        "profile_id": "profile-1",
        "name": "Core",
        "description": None,
        "sleeve_id": "sleeve-1",
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    row = CustomBasketORM(**{k: v for k, v in defaults.items() if k != "items"})
    row.items = overrides.get(
        "items",
        [
            CustomBasketItemORM(
                id="item-1",
                basket_id=defaults["id"],
                instrument_id=1,
                weight_pct=Decimal("60"),
                created_at=now,
                updated_at=now,
            ),
            CustomBasketItemORM(
                id="item-2",
                basket_id=defaults["id"],
                instrument_id=2,
                weight_pct=Decimal("40"),
                created_at=now,
                updated_at=now,
            ),
        ],
    )
    return row


class TestCustomBasketServiceCreate:
    @pytest.mark.asyncio
    async def test_create_persists_basket(self):
        db = AsyncMock()
        db.get = AsyncMock(
            return_value=SleeveORM(
                profile_id="profile-1",
                name="S",
                category="equities",
                capital_allocation_pct=Decimal("100"),
                risk_budget=Decimal("1000"),
            )
        )
        db.execute = AsyncMock(
            side_effect=[
                MagicMock(all=lambda: [(1,), (2,)]),
                MagicMock(),
            ]
        )
        service = CustomBasketService(db)
        payload = CustomBasketCreate(
            name="Growth",
            sleeve_id="sleeve-1",
            items=_items((1, "60"), (2, "40")),
        )
        mock_read = MagicMock()
        mock_read.name = "Growth"
        with patch(
            "app.services.custom_basket.service.CustomBasketRead.from_orm_row",
            return_value=mock_read,
        ):
            basket = await service.create("profile-1", payload)
        assert basket.name == "Growth"
        assert db.add.called
        assert db.flush.await_count >= 2

    @pytest.mark.asyncio
    async def test_create_rejects_unknown_sleeve(self):
        db = AsyncMock()
        db.get = AsyncMock(return_value=None)
        service = CustomBasketService(db)
        payload = CustomBasketCreate(
            name="Growth",
            sleeve_id="missing",
            items=_items((1, "100")),
        )
        with pytest.raises(CustomBasketValidationError, match="sleeve_id not found"):
            await service.create("profile-1", payload)


class TestCustomBasketServiceUpdateIntegrity:
    @pytest.mark.asyncio
    async def test_blocks_removing_instrument_with_active_intent(self):
        row = _basket_row()
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=lambda: row),
                MagicMock(all=lambda: [(2,)]),
                MagicMock(all=lambda: [(1,)]),
            ]
        )
        service = CustomBasketService(db)
        patch = CustomBasketUpdate(items=_items((2, "100")))
        with pytest.raises(CustomBasketIntegrityError, match="active deal intents"):
            await service.update("profile-1", "basket-1", patch)

    @pytest.mark.asyncio
    async def test_allows_reweight_without_removing_instruments(self):
        row = _basket_row()
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=lambda: row),
                MagicMock(all=lambda: [(1,), (2,)]),
                MagicMock(),
            ]
        )
        service = CustomBasketService(db)
        patch = CustomBasketUpdate(items=_items((1, "50"), (2, "50")))
        updated = await service.update("profile-1", "basket-1", patch)
        assert updated.name == "Core"
        assert db.flush.await_count >= 1

    @pytest.mark.asyncio
    async def test_allows_removal_when_no_active_exposure(self):
        row = _basket_row()
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=lambda: row),
                MagicMock(all=lambda: [(2,)]),
                MagicMock(all=lambda: []),
                MagicMock(),
            ]
        )
        service = CustomBasketService(db)
        patch = CustomBasketUpdate(items=_items((2, "100")))
        updated = await service.update("profile-1", "basket-1", patch)
        assert updated.name == "Core"


class TestCustomBasketServiceLookup:
    @pytest.mark.asyncio
    async def test_get_raises_when_missing(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))
        service = CustomBasketService(db)
        with pytest.raises(CustomBasketNotFoundError):
            await service.get("profile-1", "missing")


class TestActiveExposureStatuses:
    def test_includes_filled_and_executing(self):
        from app.services.custom_basket.service import ACTIVE_EXPOSURE_STATUSES

        assert DealIntentStatus.FILLED.value in ACTIVE_EXPOSURE_STATUSES
        assert DealIntentStatus.EXECUTING.value in ACTIVE_EXPOSURE_STATUSES
        assert DealIntentStatus.CANCELLED.value not in ACTIVE_EXPOSURE_STATUSES
