"""Per-user venue balances from the trading-key vault. Never platform .env keys."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.schemas.portfolio import VenueBalanceOut, VenueBalancesOut
from app.services.trading_keys.resolver import (
    UserTradingKeyNotFound,
    get_active_user_credentials,
    list_user_connected_venues,
)

logger = get_logger(__name__)


def empty_venue_balances() -> VenueBalancesOut:
    return VenueBalancesOut(
        venues=[],
        total_trading_usd=0.0,
        total_balance_usd=0.0,
        total_usd=0.0,
        as_of=datetime.now(timezone.utc).isoformat(),
    )


async def live_wallet_has_funds(db: AsyncSession, user_id: str) -> bool:
    """True only when this user's own live keys report a positive wallet.

    Paper/testnet balances do not count. Fail closed if live venues did not
    refresh — never infer live money from the demo ledger or platform .env keys.
    """
    try:
        snapshot = await build_user_venue_balances(db, user_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug("live wallet probe skipped", error=str(exc))
        return False
    live_rows = [v for v in snapshot.venues if str(v.mode or "live").lower() == "live"]
    if not any(v.refreshed for v in live_rows):
        return False
    return float(sum(v.total_usd for v in live_rows)) > 0


async def build_user_venue_balances(db: AsyncSession, user_id: str) -> VenueBalancesOut:
    """Balances for this user's connected API keys only."""
    metas = await list_user_connected_venues(db, user_id)
    venues: list[VenueBalanceOut] = []
    for meta in metas:
        venue = (meta.venue or "").lower()
        mode = meta.account_mode or "live"
        if venue == "binance":
            venues.append(await _user_binance_row(db, user_id, mode))
            continue
        if venue in ("tinkoff", "tbank"):
            venues.append(await _user_tinkoff_row(db, user_id, mode))
            continue
        if venue == "finam":
            venues.append(await _user_finam_row(db, user_id, mode))
            continue
        venues.append(
            VenueBalanceOut(
                venue=venue,
                configured=True,
                mode=mode,
                refreshed=False,
                detail="Key connected — live balance is fetched only in live mode with this user's key",
            )
        )

    total_trading = round(sum(v.trading_usd for v in venues), 2)
    total_balance = round(sum(v.balance_usd for v in venues), 2)
    total = round(sum(v.total_usd for v in venues), 2)
    return VenueBalancesOut(
        venues=venues,
        total_trading_usd=total_trading,
        total_balance_usd=total_balance,
        total_usd=total,
        as_of=datetime.now(timezone.utc).isoformat(),
    )


async def _user_binance_row(db: AsyncSession, user_id: str, account_mode: str) -> VenueBalanceOut:
    try:
        creds = await get_active_user_credentials(
            db,
            user_id=user_id,
            venue="binance",
            account_mode=account_mode,
            action="balance_read",
        )
    except UserTradingKeyNotFound:
        return VenueBalanceOut(
            venue="binance",
            configured=False,
            mode=account_mode,
            detail="no active Binance key",
        )

    payload = creds.credentials
    from app.services.portfolio.venue_balances import fetch_binance_account_balance

    return await fetch_binance_account_balance(
        api_key=str(payload.get("api_key") or ""),
        api_secret=str(payload.get("api_secret") or ""),
        base_url=payload.get("base_url"),
    )


async def _usd_rub() -> float | None:
    from app.services.market_data.moex_currency import get_moex_currency_quote

    try:
        quote = await get_moex_currency_quote("USD000UTSTOM")
    except Exception as exc:  # noqa: BLE001
        logger.debug("usd/rub quote unavailable", error=str(exc)[:120])
        return None
    price = (quote or {}).get("price")
    try:
        value = float(price)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


async def _user_tinkoff_row(db: AsyncSession, user_id: str, account_mode: str) -> VenueBalanceOut:
    """Valuation straight from T-Bank GetPortfolio with the user's own token."""
    from app.services.broker.tbank_api import TBankApiError, TBankClient, money

    try:
        creds = await get_active_user_credentials(
            db, user_id=user_id, venue="tinkoff", account_mode=account_mode, action="balance_read"
        )
    except UserTradingKeyNotFound:
        return VenueBalanceOut(venue="tinkoff", configured=False, mode=account_mode, detail="счёт не подключён")
    token = str(creds.credentials.get("token") or creds.credentials.get("api_key") or "")
    try:
        client = TBankClient(token, sandbox=account_mode != "live")
        accounts = [a for a in await client.get_accounts() if a.is_open and a.readable]
        invested = 0.0
        cash = 0.0
        for acc in accounts:
            pf = await client.get_portfolio(acc.id)
            for key in ("totalAmountShares", "totalAmountBonds", "totalAmountEtf", "totalAmountFutures",
                        "totalAmountOptions", "totalAmountSp"):
                invested += float(money(pf.get(key)) or 0)
            cash += float(money(pf.get("totalAmountCurrencies")) or 0)
    except TBankApiError as exc:
        return VenueBalanceOut(
            venue="tinkoff", configured=True, mode=account_mode, refreshed=False, detail=exc.message, error=exc.message
        )
    rate = await _usd_rub()
    if not rate:
        return VenueBalanceOut(
            venue="tinkoff",
            configured=True,
            mode=account_mode,
            refreshed=False,
            detail=f"Счёт: {invested + cash:,.0f} ₽ (нет курса доллара для пересчёта)".replace(",", " "),
        )
    return VenueBalanceOut(
        venue="tinkoff",
        configured=True,
        mode=account_mode,
        refreshed=True,
        trading_usd=round(invested / rate, 2),
        balance_usd=round(cash / rate, 2),
        total_usd=round((invested + cash) / rate, 2),
        currency="USD",
        detail=f"Счёт: {invested + cash:,.0f} ₽, в бумагах {invested:,.0f} ₽".replace(",", " "),
    )


async def _user_finam_row(db: AsyncSession, user_id: str, account_mode: str) -> VenueBalanceOut:
    """Valuation from Finam GetAccount (equity and cash) with the user's own secret."""
    from app.services.broker.finam_api import FinamApiError, FinamClient, dec, money

    try:
        creds = await get_active_user_credentials(
            db, user_id=user_id, venue="finam", account_mode=account_mode, action="balance_read"
        )
    except UserTradingKeyNotFound:
        return VenueBalanceOut(venue="finam", configured=False, mode=account_mode, detail="счёт не подключён")
    secret = str(creds.credentials.get("token") or creds.credentials.get("api_key") or "")
    equity = 0.0
    cash = 0.0
    try:
        client = FinamClient(secret)
        details = await client.token_details()
        for account_id in details.account_ids:
            acc = await client.get_account(account_id)
            equity += float(dec(acc.get("equity")) or 0)
            for c in acc.get("cash") or []:
                amount, ccy = money(c)
                if ccy == "RUB" and amount is not None:
                    cash += float(amount)
    except FinamApiError as exc:
        return VenueBalanceOut(venue="finam", configured=True, mode=account_mode, detail=exc.message, error=exc.message)
    rate = await _usd_rub()
    if not rate:
        return VenueBalanceOut(
            venue="finam", configured=True, mode=account_mode, refreshed=False,
            detail=f"Счёт: {equity:,.0f} ₽ (нет курса доллара для пересчёта)".replace(",", " "),
        )
    invested = max(0.0, equity - cash)
    return VenueBalanceOut(
        venue="finam",
        configured=True,
        mode=account_mode,
        refreshed=True,
        trading_usd=round(invested / rate, 2),
        balance_usd=round(cash / rate, 2),
        total_usd=round(equity / rate, 2),
        currency="USD",
        detail=f"Счёт: {equity:,.0f} ₽, в бумагах {invested:,.0f} ₽".replace(",", " "),
    )
