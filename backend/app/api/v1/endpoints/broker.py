"""Read-only broker portfolio straight from T-Bank with the user's own token."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_current_user_email, get_user_db
from app.utils.cache import rate_limit_check

router = APIRouter(prefix="/broker", tags=["broker"])


@router.get("/portfolio")
async def get_broker_portfolio(
    account_mode: str = Query("live", pattern="^(paper|live)$"),
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> dict:
    """Positions and totals per open account. The platform token is never used."""
    from app.services.broker.tbank_api import TBankApiError, TBankClient, money, money_ccy
    from app.services.portfolio.user_scope import get_user_by_email
    from app.services.trading_keys.resolver import UserTradingKeyNotFound, get_active_user_credentials

    allowed, _ = await rate_limit_check(
        f"broker:{email}",
        settings.BROKER_RATE_LIMIT_PER_MINUTE,
        60,
        fail_closed=True,
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Слишком много запросов к брокеру, повторите через минуту",
        )
    user = await get_user_by_email(db, email)
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    try:
        creds = await get_active_user_credentials(
            db, user_id=user.id, venue="tinkoff", account_mode=account_mode, action="portfolio_read"
        )
    except UserTradingKeyNotFound:
        return {
            "configured": False,
            "source": "tinkoff",
            "mode": account_mode,
            "detail": "Подключите счёт Т-Банка в разделе «Брокерские счета»",
            "accounts": [],
            "positions": [],
            "total_amount": None,
        }
    token = str(creds.credentials.get("token") or creds.credentials.get("api_key") or "")
    try:
        client = TBankClient(token, sandbox=account_mode != "live")
        accounts = [a for a in await client.get_accounts() if a.is_open and a.readable]
        out_accounts = []
        positions = []
        total = 0.0
        for acc in accounts:
            pf = await client.get_portfolio(acc.id)
            acc_total = float(money(pf.get("totalAmountPortfolio")) or 0)
            total += acc_total
            out_accounts.append(
                {
                    "id": acc.id,
                    "name": acc.name,
                    "access": "full" if acc.can_trade else "read_only",
                    "total_rub": round(acc_total, 2),
                    "expected_yield_pct": float(money(pf.get("expectedYield")) or 0),
                    "daily_yield_rub": float(money(pf.get("dailyYield")) or 0),
                }
            )
            for p in pf.get("positions") or []:
                qty = money(p.get("quantity"))
                price = money(p.get("currentPrice"))
                positions.append(
                    {
                        "account_id": acc.id,
                        "figi": p.get("figi"),
                        "ticker": p.get("ticker"),
                        "class_code": p.get("classCode"),
                        "instrument_type": p.get("instrumentType"),
                        "quantity": float(qty) if qty is not None else None,
                        "average_price": float(money(p.get("averagePositionPrice")) or 0),
                        "current_price": float(price) if price is not None else None,
                        "currency": money_ccy(p.get("currentPrice")),
                        "value": float(qty * price) if qty is not None and price is not None else None,
                        "expected_yield": float(money(p.get("expectedYield")) or 0),
                        "blocked": bool(p.get("blocked")),
                    }
                )
    except TBankApiError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.message) from exc
    await db.commit()
    return {
        "configured": True,
        "source": "tinkoff",
        "mode": account_mode,
        "detail": None,
        "accounts": out_accounts,
        "positions": positions,
        "total_amount": round(total, 2),
    }
