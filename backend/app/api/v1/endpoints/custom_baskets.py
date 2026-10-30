"""CustomBasket CRUD — user instrument grouping within a profile."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user_email, get_db
from app.db.models import User
from app.domain.custom_basket import CustomBasketCreate, CustomBasketItemCreate, CustomBasketUpdate
from app.schemas.custom_basket import (
    CustomBasketCreateIn,
    CustomBasketOut,
    CustomBasketUpdateIn,
)
from app.services.custom_basket.service import (
    CustomBasketIntegrityError,
    CustomBasketNotFoundError,
    CustomBasketService,
    CustomBasketValidationError,
)

router = APIRouter(prefix="/custom-baskets", tags=["custom-baskets"])


async def _profile_id_for_email(db: AsyncSession, email: str) -> str:
    result = await db.execute(select(User.id).where(User.email == email))
    user_id = result.scalar_one_or_none()
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")
    return user_id


def _to_create(body: CustomBasketCreateIn) -> CustomBasketCreate:
    return CustomBasketCreate(
        name=body.name,
        description=body.description,
        sleeve_id=body.sleeve_id,
        items=[
            CustomBasketItemCreate(
                instrument_id=item.instrument_id,
                weight_pct=item.weight_pct,
            )
            for item in body.items
        ],
    )


def _to_update(body: CustomBasketUpdateIn) -> CustomBasketUpdate:
    items = None
    if body.items is not None:
        items = [
            CustomBasketItemCreate(
                instrument_id=item.instrument_id,
                weight_pct=item.weight_pct,
            )
            for item in body.items
        ]
    return CustomBasketUpdate(
        name=body.name,
        description=body.description,
        sleeve_id=body.sleeve_id,
        items=items,
    )


def _map_service_error(exc: Exception) -> HTTPException:
    # GA16-336: Russian client copy; exception text stays off the wire.
    if isinstance(exc, CustomBasketNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Корзина не найдена")
    if isinstance(exc, CustomBasketIntegrityError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Нельзя сохранить корзину: конфликт данных.",
        )
    if isinstance(exc, CustomBasketValidationError):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Проверьте состав корзины и попробуйте снова.",
        )
    raise exc


@router.get(
    "",
    response_model=list[CustomBasketOut],
    summary="List custom baskets for the authenticated profile",
)
async def list_custom_baskets(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> list[CustomBasketOut]:
    profile_id = await _profile_id_for_email(db, email)
    service = CustomBasketService(db)
    baskets = await service.list_for_profile(profile_id)
    return [CustomBasketOut.model_validate(b) for b in baskets]


@router.post(
    "",
    response_model=CustomBasketOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a custom basket",
    description=(
        "Analytics/grouping unit only — each instrument still executes via its own DealIntent. "
        "Optional sleeve_id attaches basket context to a sleeve without replacing sleeve allocation."
    ),
)
async def create_custom_basket(
    body: CustomBasketCreateIn,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> CustomBasketOut:
    profile_id = await _profile_id_for_email(db, email)
    service = CustomBasketService(db)
    try:
        basket = await service.create(profile_id, _to_create(body))
    except (CustomBasketValidationError, CustomBasketIntegrityError) as exc:
        raise _map_service_error(exc) from exc
    await db.commit()
    return CustomBasketOut.model_validate(basket)


@router.get(
    "/{basket_id}",
    response_model=CustomBasketOut,
    summary="Get a custom basket by id",
)
async def get_custom_basket(
    basket_id: str,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> CustomBasketOut:
    profile_id = await _profile_id_for_email(db, email)
    service = CustomBasketService(db)
    try:
        basket = await service.get(profile_id, basket_id)
    except CustomBasketNotFoundError as exc:
        raise _map_service_error(exc) from exc
    return CustomBasketOut.model_validate(basket)


@router.patch(
    "/{basket_id}",
    response_model=CustomBasketOut,
    summary="Update a custom basket",
    description="Composition changes block removal of instruments with active deal intents in the linked sleeve.",
)
async def update_custom_basket(
    basket_id: str,
    body: CustomBasketUpdateIn,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> CustomBasketOut:
    profile_id = await _profile_id_for_email(db, email)
    service = CustomBasketService(db)
    try:
        basket = await service.update(profile_id, basket_id, _to_update(body))
    except (CustomBasketNotFoundError, CustomBasketValidationError, CustomBasketIntegrityError) as exc:
        raise _map_service_error(exc) from exc
    await db.commit()
    return CustomBasketOut.model_validate(basket)


@router.delete(
    "/{basket_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a custom basket",
)
async def delete_custom_basket(
    basket_id: str,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> None:
    profile_id = await _profile_id_for_email(db, email)
    service = CustomBasketService(db)
    try:
        await service.delete(profile_id, basket_id)
    except (CustomBasketNotFoundError, CustomBasketIntegrityError) as exc:
        raise _map_service_error(exc) from exc
    await db.commit()
