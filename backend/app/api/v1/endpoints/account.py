"""Personal cabinet API — profile, portfolios, paper balance transfers."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access_deps import require_paid_subscription
from app.core.deps import get_current_user_email, get_user_db
from app.schemas.account import (
    AccountSummaryOut,
    PaperTransferIn,
    PaperTransferOut,
)
from app.services.account.service import (
    get_account_summary,
    paper_deposit,
    paper_withdraw,
)
from app.services.portfolio.user_scope import get_user_by_email
from app.services.two_factor import consume_reauth_token

router = APIRouter(prefix="/account", tags=["account"])


async def _require_withdraw_reauth(
    email: str, db: AsyncSession, reauth_token: str | None
) -> None:
    user = await get_user_by_email(db, email)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if not bool(getattr(user, "two_factor_enabled", False)):
        return
    if not await consume_reauth_token(user.id, reauth_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Подтвердите вывод кодом 2FA (reauth).",
        )


@router.get("", response_model=AccountSummaryOut)
async def get_account(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> AccountSummaryOut:
    """Personal info, balance breakdown, and portfolio list."""
    return await get_account_summary(email, db)


@router.get("/profile", response_model=AccountSummaryOut)
async def get_profile(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> AccountSummaryOut:
    """Alias for account summary (profile + balance + portfolios)."""
    return await get_account_summary(email, db)


@router.post("/deposit", response_model=PaperTransferOut)
async def deposit_paper_balance(
    body: PaperTransferIn,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
    _paid: object = Depends(require_paid_subscription),
) -> PaperTransferOut:
    """Simulated top-up in paper trading mode."""
    return await paper_deposit(email, body.amount_usd, db)


@router.post("/withdraw", response_model=PaperTransferOut)
async def withdraw_paper_balance(
    body: PaperTransferIn,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
    _paid: object = Depends(require_paid_subscription),
) -> PaperTransferOut:
    """Simulated withdrawal of free balance in paper trading mode."""
    await _require_withdraw_reauth(email, db, body.reauth_token)
    return await paper_withdraw(email, body.amount_usd, db)
