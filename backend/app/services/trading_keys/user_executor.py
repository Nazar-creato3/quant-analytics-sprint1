"""Resolve execution venue and build per-user executors via ExecutionProvider (Flow B)."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.services.execution.adapter import (
    ExecutorProtocol,
    PaperExecutor,
    requires_broker_paper_simulation,
)
from app.services.execution.providers.bridge import wrap_provider
from app.services.execution.providers.registry import ExecutionMode, get_execution_provider_for_user
from app.services.execution.symbol_mapping import resolve_symbol_route
from app.services.execution.tokenized_provider_type import TOKENIZED_EQUITY_VENUE
from app.services.trading_keys.resolver import UserTradingKeyNotFound, get_active_user_credentials
from app.services.trading_keys.tokenized_resolver import get_tokenized_equity_credentials
from app.utils.cache import cache_get
from app.utils.helpers import get_user_settings_key

logger = get_logger(__name__)


class TradingKeyRequiredError(Exception):
    def __init__(self, venue: str, message: str | None = None) -> None:
        self.venue = venue
        super().__init__(
            message
            or f"Connect {venue} in Settings -> Trading accounts to execute trades"
        )


class LiveTradingUnavailable(TradingKeyRequiredError):
    """The caller asked for a real-account order this user cannot place now."""

    def __init__(self, message: str) -> None:
        super().__init__("live", message)


async def _preferred_tokenized_provider(db: AsyncSession, user_id: str, email: str | None = None) -> str:
    del db, user_id, email
    return "bybit"


def resolve_execution_venue(ticker: str, *, provider_type: str = "bybit") -> str:
    route = resolve_symbol_route(ticker, provider_type=provider_type)
    return route.execution_venue


_LIVE_ACCESS_LEVELS = frozenset(
    {
        "approved_live",
        "restricted_live",
        "managed_account",
        "enterprise",
    }
)


def resolve_account_mode() -> str:
    """Global fallback. Prefer resolve_user_account_mode for execution."""
    return "live" if settings.live_trading_unlocked else "paper"


async def user_has_full_trading_grant(db: AsyncSession, user_id: str) -> bool:
    """True after Admissions full-access (or staff). Trial / paper users never qualify.

    Payment webhooks should call admissions grant_full_access — not this check alone.
    """
    from app.db.models import User
    from app.domain.rbac import is_staff_admin_role, map_legacy_user_role
    from app.services.access_policy.service import access_policy_service

    policy = await access_policy_service.read(db, user_id)
    level = str(getattr(policy.access_level, "value", policy.access_level))
    if level in _LIVE_ACCESS_LEVELS:
        return True
    user = await db.get(User, user_id)
    if user is not None and is_staff_admin_role(map_legacy_user_role(str(user.role))):
        return True
    return False


async def resolve_user_account_mode(db: AsyncSession, user_id: str) -> str:
    """Live only: platform live on + Admissions/staff grant + the user's own keys."""
    if not settings.live_trading_unlocked:
        return "paper"
    if not await user_has_full_trading_grant(db, user_id):
        return "paper"
    if not await user_has_trading_key(db, user_id, account_mode="live"):
        return "paper"
    from app.services.portfolio.user_venue_balances import live_wallet_has_funds

    # Live keys with an empty wallet are not a live account. Stay on the demo
    # book (PaperExecutor + paper ledger). Do not require exchange sandboxes.
    if not await live_wallet_has_funds(db, user_id):
        return "paper"
    return "live"


async def live_unavailable_reason(db: AsyncSession, user_id: str) -> str | None:
    """Why this user cannot trade on a real account right now (Russian), or None."""
    from app.services.legal.gates import real_orders_allowed

    if not real_orders_allowed():
        return "Сделки на реальном счёте сейчас недоступны. Переключитесь в «Учебный»."
    if not settings.live_trading_unlocked:
        return "Реальная торговля на платформе пока выключена. Переключитесь в «Учебный»."
    if not await user_has_full_trading_grant(db, user_id):
        return "Для сделок на реальном счёте нужен подтверждённый доступ к реальной торговле."
    if not await user_has_trading_key(db, user_id, account_mode="live"):
        return "Подключите боевой счёт брокера с правом на сделки."
    from app.services.portfolio.user_venue_balances import live_wallet_has_funds

    if not await live_wallet_has_funds(db, user_id):
        return "На боевом счёте нет средств или брокер не ответил."
    return None


async def _effective_execution_mode(
    db: AsyncSession,
    user_id: str,
    requested: str | None,
) -> str:
    """Callers cannot escalate to live. They may only force paper."""
    allowed = await resolve_user_account_mode(db, user_id)
    if allowed != "live":
        if requested and requested.lower() == "live":
            # An explicit live request must never turn into a silent paper fill.
            reason = await live_unavailable_reason(db, user_id) or "Реальная торговля недоступна"
            logger.warning("Blocked live execution", user_id=user_id, reason=reason)
            raise LiveTradingUnavailable(reason)
        return "paper"
    if requested and requested.lower() == "paper":
        return "paper"
    return "live"


async def get_user_executor(
    db: AsyncSession,
    *,
    user_id: str,
    ticker: str,
    account_mode: str | None = None,
    user_email: str | None = None,
) -> ExecutorProtocol:
    mode = await _effective_execution_mode(db, user_id, account_mode)
    pref = await _preferred_tokenized_provider(db, user_id, user_email)
    route = resolve_symbol_route(ticker, provider_type=pref)
    tokenized = route.execution_venue == "tokenized_equity"
    if requires_broker_paper_simulation(mode):
        logger.info(
            "Paper simulation — blocking real broker",
            user_id=user_id,
            ticker=ticker,
            account_mode=mode,
            tokenized=tokenized,
        )
        return PaperExecutor()

    logger.info(
        "get_user_executor",
        user_id=user_id,
        ticker=ticker,
        provider_type=pref,
        execution_venue=route.execution_venue,
    )

    if route.execution_venue == "tokenized_equity":
        from app.services.legal.gates import foreign_venues_live_allowed

        if not foreign_venues_live_allowed():
            raise LiveTradingUnavailable("Реальные сделки на этой площадке недоступны. Доступен учебный режим.")
        provider, exec_mode = await get_execution_provider_for_user(
            db,
            user_id=user_id,
            ticker=ticker,
            account_mode=mode,
            preferred_provider=pref,
        )
        return wrap_provider(provider, mode=exec_mode.value, account_mode=mode)

    venue = route.execution_venue
    from app.services.legal.gates import FOREIGN_LIVE_VENUES, foreign_venues_live_allowed

    if venue in FOREIGN_LIVE_VENUES and not foreign_venues_live_allowed():
        raise LiveTradingUnavailable("Реальные сделки на этой площадке недоступны. Доступен учебный режим.")
    if venue in ("tinkoff", "tbank") and not await user_has_trading_key(db, user_id, venue="tinkoff", account_mode=mode):
        # Moscow Exchange through Finam when that is the broker the user connected.
        if await user_has_trading_key(db, user_id, venue="finam", account_mode=mode):
            venue = "finam"
    try:
        creds = await get_active_user_credentials(
            db,
            user_id=user_id,
            venue=venue,
            account_mode=mode,
            action="order_execution",
        )
    except UserTradingKeyNotFound as exc:
        raise TradingKeyRequiredError(venue) from exc

    payload = creds.credentials
    if venue == "binance":
        from app.services.trading_keys.executors import BinanceUserExecutor

        return BinanceUserExecutor(
            api_key=payload.get("api_key", ""),
            api_secret=payload.get("api_secret", ""),
            base_url=payload.get("base_url"),
            account_mode=mode,
        )
    if venue in ("tinkoff", "tbank"):
        from app.services.broker.tinkoff_orders import TinkoffExecutor

        return TinkoffExecutor(
            token=payload.get("token", payload.get("api_key", "")),
            sandbox=mode != "live",
            user_id=user_id,
        )

    if venue == "finam":
        from app.services.broker.finam_orders import FinamExecutor

        return FinamExecutor(
            secret=payload.get("token", payload.get("api_key", "")),
            sandbox=mode != "live",
            user_id=user_id,
        )

    raise TradingKeyRequiredError(venue, f"Сделки через {venue} не поддерживаются")


async def get_user_execution_mode(
    db: AsyncSession,
    *,
    user_id: str,
    ticker: str,
    account_mode: str | None = None,
    user_email: str | None = None,
) -> ExecutionMode:
    pref = await _preferred_tokenized_provider(db, user_id, user_email)
    mode = await _effective_execution_mode(db, user_id, account_mode)
    _, exec_mode = await get_execution_provider_for_user(
        db,
        user_id=user_id,
        ticker=ticker,
        account_mode=mode,
        preferred_provider=pref,
    )
    return exec_mode


async def user_has_trading_key(
    db: AsyncSession,
    user_id: str,
    *,
    venue: str | None = None,
    account_mode: str | None = None,
) -> bool:
    mode = account_mode or resolve_account_mode()
    venues = [venue] if venue else ["binance", TOKENIZED_EQUITY_VENUE, "bybit", "mexc", "tinkoff", "finam"]
    for v in venues:
        try:
            if v in (TOKENIZED_EQUITY_VENUE, "bybit", "mexc"):
                await get_tokenized_equity_credentials(
                    db, user_id=user_id, account_mode=mode, action="key_probe"
                )
                return True
            await get_active_user_credentials(
                db, user_id=user_id, venue=v, account_mode=mode, action="key_probe"
            )
            return True
        except UserTradingKeyNotFound:
            continue
    return False
