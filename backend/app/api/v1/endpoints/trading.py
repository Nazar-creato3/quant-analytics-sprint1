
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user_email
from app.db.session import get_db
from app.db.models import TradingAccount, TradingStrategy, User
from app.schemas.accounts import (
    TradingAccountCreate,
    TradingAccountUpdate,
    TradingAccountRead,
)

from app.schemas.trading import (
    TradingStrategyCreate,
    TradingStrategyRead,
)

# JWT required on every trading route (any authenticated user; roles later).
router = APIRouter(
    prefix="/trading",
    tags=["trading"],
    dependencies=[Depends(get_current_user_email)],
)

FAKE_USER_ID = "00000000-0000-0000-0000-000000000001"  # legacy rows only


async def _resolve_user_id(email: str, db: AsyncSession) -> str:
    result = await db.execute(select(User).where(User.email == email.lower()))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user.id


# ── Trading Accounts ─────────────────────────────────────────────────────────


@router.post(
    "/accounts",
    response_model=TradingAccountRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_account(
    payload: TradingAccountCreate,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
):
    user_id = await _resolve_user_id(email, db)
    account = TradingAccount(
        user_id=user_id,
        name=payload.name,
        base_currency=payload.base_currency,
        mode=payload.mode.value if hasattr(payload.mode, "value") else payload.mode,
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return account


@router.get(
    "/accounts",
    response_model=List[TradingAccountRead],
)
async def list_accounts(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
):
    user_id = await _resolve_user_id(email, db)
    stmt = select(TradingAccount).where(TradingAccount.user_id == user_id)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get(
    "/accounts/{account_id}",
    response_model=TradingAccountRead,
)
async def get_account(
    account_id: str,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
):
    user_id = await _resolve_user_id(email, db)
    stmt = select(TradingAccount).where(
        TradingAccount.id == account_id,
        TradingAccount.user_id == user_id,
    )
    result = await db.execute(stmt)
    account = result.scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


@router.patch(
    "/accounts/{account_id}",
    response_model=TradingAccountRead,
)
async def update_account(
    account_id: str,
    payload: TradingAccountUpdate,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
):
    user_id = await _resolve_user_id(email, db)
    stmt = select(TradingAccount).where(
        TradingAccount.id == account_id,
        TradingAccount.user_id == user_id,
    )
    result = await db.execute(stmt)
    account = result.scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")

    data = payload.dict(exclude_unset=True)
    for field, value in data.items():
        if field == "mode" and hasattr(value, "value"):
            value = value.value
        setattr(account, field, value)

    db.add(account)
    await db.commit()
    await db.refresh(account)
    return account


@router.delete(
    "/accounts/{account_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_account(
    account_id: str,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
):
    user_id = await _resolve_user_id(email, db)
    stmt = select(TradingAccount).where(
        TradingAccount.id == account_id,
        TradingAccount.user_id == user_id,
    )
    result = await db.execute(stmt)
    account = result.scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")

    await db.delete(account)
    await db.commit()
    return


# ── Trading Strategies ───────────────────────────────────────────────────────


@router.post(
    "/strategies",
    response_model=TradingStrategyRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_strategy(
    payload: TradingStrategyCreate,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
):
    user_id = await _resolve_user_id(email, db)
    stmt = select(TradingAccount).where(
        TradingAccount.id == payload.account_id,
        TradingAccount.user_id == user_id,
    )
    result = await db.execute(stmt)
    account = result.scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=404, detail="TradingAccount not found")

    strategy = TradingStrategy(
        user_id=user_id,
        account_id=payload.account_id,
        name=payload.name,
        description=payload.description,
        is_active=payload.is_active,
    )
    db.add(strategy)
    await db.commit()
    await db.refresh(strategy)
    return strategy


@router.get(
    "/strategies",
    response_model=List[TradingStrategyRead],
)
async def list_strategies(
    account_id: Optional[str] = None,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
):
    user_id = await _resolve_user_id(email, db)
    stmt = select(TradingStrategy).where(TradingStrategy.user_id == user_id)
    if account_id is not None:
        stmt = stmt.where(TradingStrategy.account_id == account_id)
    result = await db.execute(stmt)
    return result.scalars().all()
