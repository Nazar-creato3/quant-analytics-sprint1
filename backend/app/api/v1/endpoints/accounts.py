from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import TradingAccount
from app.db.session import get_db
from app.schemas.accounts import (
    TradingAccountCreate,
    TradingAccountRead,
    TradingAccountUpdate,
)

router = APIRouter(prefix="/accounts", tags=["accounts"])


# TODO: пока юзера жёстко захардкодим, потом привяжем к auth
FAKE_USER_ID = "00000000-0000-0000-0000-000000000001"


@router.post(
    "/",
    response_model=TradingAccountRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_account(
    payload: TradingAccountCreate,
    db: AsyncSession = Depends(get_db),
):
    account = TradingAccount(
        user_id=FAKE_USER_ID,
        name=payload.name,
        base_currency=payload.base_currency,
        mode=payload.mode.value if hasattr(payload.mode, "value") else payload.mode,
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return account


@router.get(
    "/",
    response_model=List[TradingAccountRead],
)
async def list_accounts(
    db: AsyncSession = Depends(get_db),
):
    stmt = select(TradingAccount).where(TradingAccount.user_id == FAKE_USER_ID)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get(
    "/{account_id}",
    response_model=TradingAccountRead,
)
async def get_account(
    account_id: str,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(TradingAccount).where(
        TradingAccount.id == account_id,
        TradingAccount.user_id == FAKE_USER_ID,
    )
    result = await db.execute(stmt)
    account = result.scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


@router.patch(
    "/{account_id}",
    response_model=TradingAccountRead,
)
async def update_account(
    account_id: str,
    payload: TradingAccountUpdate,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(TradingAccount).where(
        TradingAccount.id == account_id,
        TradingAccount.user_id == FAKE_USER_ID,
    )
    result = await db.execute(stmt)
    account = result.scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")

    data = payload.dict(exclude_unset=True)
    for field, value in data.items():
        # mode может быть Enum, аккуратно извлекаем value
        if field == "mode" and hasattr(value, "value"):
            value = value.value
        setattr(account, field, value)

    db.add(account)
    await db.commit()
    await db.refresh(account)
    return account


@router.delete(
    "/{account_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_account(
    account_id: str,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(TradingAccount).where(
        TradingAccount.id == account_id,
        TradingAccount.user_id == FAKE_USER_ID,
    )
    result = await db.execute(stmt)
    account = result.scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")

    await db.delete(account)
    await db.commit()
    return
