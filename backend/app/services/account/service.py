"""Personal cabinet — profile, portfolios, paper balance transfers."""
from __future__ import annotations

from collections import defaultdict

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints.settings import _defaults as settings_defaults
from app.core.config import settings
from app.db.models import Maneuver, ManeuverStatus, TradingAccount, User
from app.schemas.account import (
    AccountBalanceOut,
    AccountSummaryOut,
    AccountUserOut,
    PaperTransferOut,
    PortfolioOut,
    PortfolioPositionOut,
)
from app.services.portfolio.metrics import (
    build_portfolio_metrics,
    set_user_paper_equity,
    _user_paper_equity,
)
from app.utils.cache import cache_get, cache_set
from app.utils.helpers import get_user_settings_key

SETTINGS_TTL = 60 * 60 * 24 * 365


def _market_value_usd(raw: object) -> float | None:
    """GA16-308: missing price stays None — never coerce to 0 USD."""
    if raw is None or raw == "":
        return None
    return float(raw)


def _sum_known_usd(positions: list[PortfolioPositionOut]) -> float | None:
    known = [p.market_value_usd for p in positions if p.market_value_usd is not None]
    if not known:
        return None
    return round(sum(known), 2)


def _display_name(email: str) -> str:
    local = email.split("@", 1)[0]
    return local.replace(".", " ").replace("_", " ").strip().title() or email


async def _get_user(email: str, db: AsyncSession) -> User:
    result = await db.execute(select(User).where(User.email == email.lower()))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


async def _metrics_to_balance(email: str, db: AsyncSession) -> AccountBalanceOut:
    metrics = await build_portfolio_metrics(email, db)
    return AccountBalanceOut(
        total_usd=metrics.total_usd,
        free_usd=metrics.balance_usd,
        locked_usd=metrics.trading_usd,
        currency=metrics.currency,
        mode=metrics.mode,
        is_paper=metrics.mode == "paper",
        as_of=metrics.as_of,
    )


async def _paper_positions(db: AsyncSession, user_id: str) -> list[PortfolioPositionOut]:
    from app.services.portfolio.user_scope import maneuvers_for_user

    result = await db.execute(
        maneuvers_for_user(user_id).where(
            Maneuver.status.in_([ManeuverStatus.EXECUTING, ManeuverStatus.FILLED])
        )
    )
    grouped: dict[str, dict] = defaultdict(
        lambda: {"market_value_usd": 0.0, "side": "neutral", "position_count": 0}
    )
    for maneuver in result.scalars():
        bucket = grouped[maneuver.ticker]
        bucket["market_value_usd"] += float(maneuver.position_size_usd or 0)
        bucket["side"] = str(maneuver.direction)
        bucket["position_count"] += 1

    return [
        PortfolioPositionOut(
            ticker=ticker,
            market_value_usd=round(data["market_value_usd"], 2),
            side=data["side"],
            position_count=data["position_count"],
        )
        for ticker, data in sorted(grouped.items())
    ]


async def _build_portfolios(
    email: str,
    user_id: str,
    db: AsyncSession,
) -> list[PortfolioOut]:
    positions = await _paper_positions(db, user_id)
    try:
        from app.services.portfolio_book.service import positions_for, value_positions

        seen = {p.ticker for p in positions}
        for row in value_positions(positions_for(user_id=user_id, mode="paper"), {}):
            if row["ticker"] in seen:
                continue
            positions.append(
                PortfolioPositionOut(
                    ticker=str(row["ticker"]),
                    market_value_usd=_market_value_usd(row.get("value")),
                    side="long",
                    position_count=1,
                )
            )
            seen.add(row["ticker"])
    except Exception:
        pass
    metrics = await build_portfolio_metrics(email, db)

    paper = PortfolioOut(
        id="paper-main",
        name="Paper Trading",
        mode="paper",
        base_currency="USD",
        market_value_usd=metrics.trading_usd,
        positions=positions,
    )

    result = await db.execute(
        select(TradingAccount).where(TradingAccount.user_id == user_id)
    )
    accounts = result.scalars().all()
    extra = []
    for account in accounts:
        book_positions: list[PortfolioPositionOut] = []
        try:
            from app.services.portfolio_book.service import positions_for, value_positions

            mode = "live" if str(account.mode).lower() == "live" else "paper"
            valued = value_positions(positions_for(user_id=user_id, mode=mode), {})
            book_positions = [
                PortfolioPositionOut(
                    ticker=str(row["ticker"]),
                    market_value_usd=_market_value_usd(row.get("value")),
                    side="long",
                    position_count=1,
                )
                for row in valued
                if row.get("account_id") in {account.id, f"live:{account.id}"}
            ]
        except Exception:
            book_positions = []
        extra.append(
            PortfolioOut(
                id=account.id,
                name=account.name,
                mode=str(account.mode),
                base_currency=account.base_currency,
                market_value_usd=_sum_known_usd(book_positions),
                positions=book_positions,
            )
        )
    return [paper, *extra]


async def get_account_summary(email: str, db: AsyncSession) -> AccountSummaryOut:
    user = await _get_user(email, db)
    balance = await _metrics_to_balance(email, db)
    portfolios = await _build_portfolios(email, user.id, db)
    return AccountSummaryOut(
        user=AccountUserOut(
            id=user.id,
            email=user.email,
            name=_display_name(user.email),
            role=str(user.role),
            created_at=user.created_at,
            last_login=user.last_login,
        ),
        balance=balance,
        portfolios=portfolios,
    )


def _require_paper_transfers() -> None:
    if not settings.PAPER_TRADING_ENABLED or settings.live_trading_unlocked:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Simulated deposits and withdrawals are only available in paper trading mode.",
        )


async def _update_portfolio_size(email: str, new_size: float, db: AsyncSession | None = None) -> None:
    from app.services.portfolio.cap_limit import cap_exceeds_balance, clamp_cap_to_balance
    from app.services.portfolio.metrics import user_account_total_usd

    size = float(new_size)
    if db is not None:
        total = await user_account_total_usd(email, db)
        if cap_exceeds_balance(size, total):
            size = clamp_cap_to_balance(size, total)
    key = get_user_settings_key(email)
    current = await cache_get(key) or {}
    merged = {**settings_defaults(), **current, "portfolio_size": round(size, 2)}
    await cache_set(key, merged, ttl=SETTINGS_TTL)


async def paper_deposit(email: str, amount_usd: float, db: AsyncSession) -> PaperTransferOut:
    _require_paper_transfers()
    equity = await _user_paper_equity(email)
    await set_user_paper_equity(email, equity + amount_usd)
    updated = await _metrics_to_balance(email, db)
    return PaperTransferOut(
        transaction_type="deposit",
        amount_usd=round(amount_usd, 2),
        balance=updated,
        message=f"Paper deposit of ${amount_usd:,.2f} applied (simulated).",
    )


async def paper_withdraw(email: str, amount_usd: float, db: AsyncSession) -> PaperTransferOut:
    _require_paper_transfers()
    balance = await _metrics_to_balance(email, db)
    if amount_usd > balance.free_usd:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Insufficient free balance. Available: ${balance.free_usd:,.2f}",
        )
    equity = await _user_paper_equity(email)
    if amount_usd > equity:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Insufficient account balance. Available: ${equity:,.2f}",
        )
    await set_user_paper_equity(email, equity - amount_usd)
    updated = await _metrics_to_balance(email, db)
    return PaperTransferOut(
        transaction_type="withdraw",
        amount_usd=round(amount_usd, 2),
        balance=updated,
        message=f"Paper withdrawal of ${amount_usd:,.2f} applied (simulated).",
    )
