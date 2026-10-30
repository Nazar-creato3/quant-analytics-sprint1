"""CustomBasket service — CRUD and composition integrity against active positions."""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.custom_basket import (
    CustomBasketCreate,
    CustomBasketItemCreate,
    CustomBasketItemORM,
    CustomBasketORM,
    CustomBasketRead,
    CustomBasketUpdate,
    validate_basket_composition,
)
from app.domain.deal_intent import DealIntentORM
from app.domain.deal_intent_enums import DealIntentStatus
from app.domain.instrument import InstrumentORM
from app.domain.sleeve import SleeveORM
from app.utils.helpers import utcnow

ACTIVE_EXPOSURE_STATUSES: frozenset[str] = frozenset(
    status.value
    for status in (
        DealIntentStatus.PENDING_APPROVAL,
        DealIntentStatus.APPROVED,
        DealIntentStatus.HELD,
        DealIntentStatus.EXECUTING,
        DealIntentStatus.FILLED,
    )
)


class CustomBasketNotFoundError(LookupError):
    """Raised when a basket does not exist for the given profile."""


class CustomBasketValidationError(ValueError):
    """Raised when basket fields or composition fail validation."""


class CustomBasketIntegrityError(CustomBasketValidationError):
    """Raised when a composition change would break active position integrity."""


class CustomBasketService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def list_for_profile(self, profile_id: str) -> list[CustomBasketRead]:
        result = await self._db.execute(
            select(CustomBasketORM)
            .where(CustomBasketORM.profile_id == profile_id)
            .options(selectinload(CustomBasketORM.items))
            .order_by(CustomBasketORM.created_at)
        )
        return [CustomBasketRead.from_orm_row(row) for row in result.scalars().all()]

    async def get(self, profile_id: str, basket_id: str) -> CustomBasketRead:
        row = await self._load_basket(profile_id, basket_id)
        return CustomBasketRead.from_orm_row(row)

    async def create(self, profile_id: str, payload: CustomBasketCreate) -> CustomBasketRead:
        try:
            validate_basket_composition(payload.items)
        except ValueError as exc:
            raise CustomBasketValidationError(str(exc)) from exc

        await self._validate_sleeve(profile_id, payload.sleeve_id)
        await self._validate_instrument_ids([item.instrument_id for item in payload.items])

        now = utcnow()
        row = CustomBasketORM(
            profile_id=profile_id,
            name=payload.name,
            description=payload.description,
            sleeve_id=payload.sleeve_id,
            created_at=now,
            updated_at=now,
        )
        self._db.add(row)
        await self._db.flush()
        await self._replace_items(row, payload.items, now=now)
        await self._db.flush()
        await self._db.refresh(row, attribute_names=["items"])
        return CustomBasketRead.from_orm_row(row)

    async def update(
        self,
        profile_id: str,
        basket_id: str,
        patch: CustomBasketUpdate,
    ) -> CustomBasketRead:
        row = await self._load_basket(profile_id, basket_id)
        patch_data = patch.model_dump(exclude_unset=True)

        if "sleeve_id" in patch_data:
            await self._validate_sleeve(profile_id, patch.sleeve_id)

        if patch.items is not None:
            try:
                validate_basket_composition(patch.items)
            except ValueError as exc:
                raise CustomBasketValidationError(str(exc)) from exc

            await self._validate_instrument_ids([item.instrument_id for item in patch.items])
            await self._ensure_composition_integrity(
                row,
                patch.items,
                sleeve_id=patch.sleeve_id if "sleeve_id" in patch_data else row.sleeve_id,
            )

        if patch.name is not None:
            row.name = patch.name
        if "description" in patch_data:
            row.description = patch.description
        if "sleeve_id" in patch_data:
            row.sleeve_id = patch.sleeve_id

        now = utcnow()
        row.updated_at = now

        if patch.items is not None:
            await self._replace_items(row, patch.items, now=now)

        await self._db.flush()
        await self._db.refresh(row, attribute_names=["items"])
        return CustomBasketRead.from_orm_row(row)

    async def delete(self, profile_id: str, basket_id: str) -> None:
        row = await self._load_basket(profile_id, basket_id)
        sleeve_id = row.sleeve_id
        if sleeve_id is not None and row.items:
            await self._ensure_no_active_exposure_for_instruments(
                sleeve_id=sleeve_id,
                instrument_ids={item.instrument_id for item in row.items},
                action="delete basket with active exposure",
            )
        await self._db.delete(row)

    async def _load_basket(self, profile_id: str, basket_id: str) -> CustomBasketORM:
        result = await self._db.execute(
            select(CustomBasketORM)
            .where(
                CustomBasketORM.id == basket_id,
                CustomBasketORM.profile_id == profile_id,
            )
            .options(selectinload(CustomBasketORM.items))
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise CustomBasketNotFoundError(f"custom basket not found: {basket_id}")
        return row

    async def _validate_sleeve(self, profile_id: str, sleeve_id: str | None) -> None:
        if sleeve_id is None:
            return
        sleeve = await self._db.get(SleeveORM, sleeve_id)
        if sleeve is None:
            raise CustomBasketValidationError(f"sleeve_id not found: {sleeve_id}")
        if sleeve.profile_id != profile_id:
            raise CustomBasketValidationError(
                f"sleeve {sleeve_id} does not belong to profile {profile_id}"
            )

    async def _validate_instrument_ids(self, instrument_ids: list[int]) -> None:
        if not instrument_ids:
            return
        result = await self._db.execute(
            select(InstrumentORM.id).where(InstrumentORM.id.in_(instrument_ids))
        )
        found = {row[0] for row in result.all()}
        missing = set(instrument_ids) - found
        if missing:
            raise CustomBasketValidationError(
                f"unknown instrument_ids: {sorted(missing)}"
            )

    async def _replace_items(
        self,
        row: CustomBasketORM,
        items: list[CustomBasketItemCreate],
        *,
        now,
    ) -> None:
        await self._db.execute(
            delete(CustomBasketItemORM).where(CustomBasketItemORM.basket_id == row.id)
        )
        for item in items:
            self._db.add(
                CustomBasketItemORM(
                    basket_id=row.id,
                    instrument_id=item.instrument_id,
                    weight_pct=item.weight_pct,
                    created_at=now,
                    updated_at=now,
                )
            )

    async def _ensure_composition_integrity(
        self,
        row: CustomBasketORM,
        new_items: list[CustomBasketItemCreate],
        *,
        sleeve_id: str | None,
    ) -> None:
        if sleeve_id is None:
            return

        current_ids = {item.instrument_id for item in row.items}
        new_ids = {item.instrument_id for item in new_items}
        removed = current_ids - new_ids
        if not removed:
            return

        await self._ensure_no_active_exposure_for_instruments(
            sleeve_id=sleeve_id,
            instrument_ids=removed,
            action="remove instruments from basket",
        )

    async def _ensure_no_active_exposure_for_instruments(
        self,
        *,
        sleeve_id: str,
        instrument_ids: set[int],
        action: str,
    ) -> None:
        if not instrument_ids:
            return

        result = await self._db.execute(
            select(DealIntentORM.instrument_id)
            .where(
                DealIntentORM.sleeve_id == sleeve_id,
                DealIntentORM.instrument_id.in_(instrument_ids),
                DealIntentORM.status.in_(ACTIVE_EXPOSURE_STATUSES),
            )
            .distinct()
        )
        blocked = sorted({row[0] for row in result.all()})
        if blocked:
            raise CustomBasketIntegrityError(
                f"cannot {action}: active deal intents exist for instruments {blocked} "
                f"in sleeve {sleeve_id!r}"
            )