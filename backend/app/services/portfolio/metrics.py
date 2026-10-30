"""Aggregate portfolio capital metrics for cockpit NavBar."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints.settings import _defaults as settings_defaults
from app.core.config import settings
from app.core.logging import get_logger
from app.schemas.portfolio import PortfolioMetricsOut
from app.services.portfolio.exposure import current_exposure, reconcile_stale_grid_exposure
from app.services.portfolio.live_equity import compute_live_pnl
from app.utils.cache import cache_delete, cache_get, cache_set
from app.utils.helpers import get_user_settings_key

logger = get_logger(__name__)

_LAST_GOOD_METRICS_KEY = "portfolio:last_good_metrics:{email}"
_EMPTY_METRICS_STREAK_KEY = "portfolio:empty_metrics_streak:{email}"
_EMPTY_METRICS_CONFIRM_TICKS = 2


def _metrics_book_is_flat(trading_usd: float, open_maneuvers: int) -> bool:
    return float(trading_usd or 0) <= 0.01 and int(open_maneuvers or 0) <= 0


async def clear_portfolio_metrics_holdback(email: str | None) -> None:
    """Drop last-good navbar snapshot after a real close/flatten."""
    if not email:
        return
    key_email = email.lower()
    await cache_delete(_LAST_GOOD_METRICS_KEY.format(email=key_email))
    await cache_delete(_EMPTY_METRICS_STREAK_KEY.format(email=key_email))


async def _holdback_transient_flat_book(
    email: str,
    metrics: PortfolioMetricsOut,
) -> PortfolioMetricsOut:
    """Ignore a one-off empty exposure tick so TRD/SUM do not flicker to cash-only."""
    key_email = email.lower()
    last_key = _LAST_GOOD_METRICS_KEY.format(email=key_email)
    streak_key = _EMPTY_METRICS_STREAK_KEY.format(email=key_email)

    if not _metrics_book_is_flat(metrics.trading_usd, metrics.open_maneuvers):
        await cache_set(last_key, metrics.model_dump(mode="json"), ttl=60 * 60)
        await cache_set(streak_key, 0, ttl=120)
        return metrics

    prev = await cache_get(last_key)
    if not isinstance(prev, dict):
        return metrics
    if _metrics_book_is_flat(float(prev.get("trading_usd") or 0), int(prev.get("open_maneuvers") or 0)):
        return metrics

    streak = int(await cache_get(streak_key) or 0) + 1
    await cache_set(streak_key, streak, ttl=120)
    if streak < _EMPTY_METRICS_CONFIRM_TICKS:
        logger.warning(
            "held back empty portfolio metrics tick",
            email=email,
            streak=streak,
            next_total=metrics.total_usd,
        )
        held = {**prev, "as_of": metrics.as_of}
        try:
            return PortfolioMetricsOut.model_validate(held)
        except Exception as exc:  # noqa: BLE001
            logger.debug("last-good metrics replay skipped", error=str(exc))
            return metrics

    await cache_set(last_key, metrics.model_dump(mode="json"), ttl=60 * 60)
    await cache_set(streak_key, 0, ttl=120)
    return metrics


async def _user_settings_merged(email: str) -> dict:
    key = get_user_settings_key(email)
    stored = await cache_get(key)
    return {**settings_defaults(), **(stored or {})}


async def _user_portfolio_size(email: str) -> float:
    merged = await _user_settings_merged(email)
    return float(merged.get("portfolio_size", settings.DEFAULT_PORTFOLIO_SIZE))


async def _ledger_total_usd(email: str, db: AsyncSession) -> float:
    """Paper/internal SUM: free cash + money in positions (not the deploy cap)."""
    from app.services.portfolio.user_scope import get_user_by_email

    equity_base = await _user_paper_equity(email, db)
    user = await get_user_by_email(db, email)
    owner_user_id = user.id if user else None
    snapshot = await current_exposure(
        db,
        owner_user_id=owner_user_id,
        owner_email=email,
    )
    live = await compute_live_pnl(
        db,
        owner_user_id=owner_user_id,
        owner_email=email,
    )
    return round(
        float(equity_base) + float(live.realized_closed_usd) + float(live.unrealized_total_usd),
        2,
    )


async def _seed_empty_demo_book(email: str, db: AsyncSession) -> float:
    """Create simulated demo cash when the paper book is empty.

    Live wallets are never credited. This is fake money for paper trading only.
    """
    from app.services.settings.new_user_defaults import DEMO_PAPER_EQUITY_USD

    await set_user_paper_equity(email, DEMO_PAPER_EQUITY_USD)
    return await _ledger_total_usd(email, db)


async def user_account_total_usd(email: str, db: AsyncSession) -> float:
    """Money on the book the user is actually trading.

    Demo/paper: internal ledger (seeded if the account never got demo cash).
    Live: venue wallets only after they hold funds. An empty live wallet must
    not zero the cap. Exchange sandbox keys are not required for demo.
    """
    from app.services.portfolio.user_scope import get_user_by_email
    from app.services.trading_keys.user_executor import resolve_user_account_mode

    user = await get_user_by_email(db, email)
    account_mode = "paper"
    if user:
        account_mode = await resolve_user_account_mode(db, user.id)
    if account_mode == "live" and user:
        _cash, venue_total = await _venue_account_totals(
            db, user_id=user.id, account_mode="live"
        )
        if venue_total is not None and venue_total > 0:
            return float(venue_total)
    paper_total = await _ledger_total_usd(email, db)
    if paper_total > 0:
        return paper_total
    stored = await cache_get(get_user_settings_key(email))
    # Redis miss must not overwrite a real book with a fresh $10k seed.
    if stored is None or "paper_equity_usd" in stored:
        return paper_total
    return await _seed_empty_demo_book(email, db)


async def _user_effective_deploy_cap(email: str, db: AsyncSession) -> float:
    """Operator deploy cap for sizing: settings, never above cash, never $10k over a small cap."""
    from app.services.risk.portfolio_sizing import resolve_deploy_cap_for_sizing

    stored = await _user_portfolio_size(email)
    total = await user_account_total_usd(email, db)
    return resolve_deploy_cap_for_sizing(stored, total)


async def _user_paper_equity(email: str, db: AsyncSession | None = None) -> float:
    """Paper deposits only. Never use portfolio_size (cap) as if it were cash."""
    merged = await _user_settings_merged(email)
    if "paper_equity_usd" in merged:
        return float(merged["paper_equity_usd"] or 0.0)
    # Closed P&L is applied later in _internal_metrics; starting cash is 0, not the cap.
    return 0.0


async def set_user_paper_equity(email: str, value: float) -> None:
    from app.api.v1.endpoints.settings import SETTINGS_TTL

    key = get_user_settings_key(email)
    current = await cache_get(key) or {}
    merged = {**settings_defaults(), **current, "paper_equity_usd": round(max(0.0, value), 2)}
    await cache_set(key, merged, ttl=SETTINGS_TTL)


async def _user_confidence_threshold(email: str) -> float:
    merged = await _user_settings_merged(email)
    return float(merged.get("confidence_threshold", settings.NO_TRADE_CONFIDENCE_THRESHOLD))


async def _should_use_platform_alpaca_metrics(email: str) -> bool:
    """Platform Alpaca is not a user ledger — never attach it to NavBar balances."""
    del email
    return False


async def _alpaca_metrics() -> PortfolioMetricsOut | None:
    if not settings.ALPACA_API_KEY or not settings.ALPACA_SECRET_KEY:
        return None
    if not settings.live_trading_unlocked:
        return None

    try:
        from app.services.execution.adapter import AlpacaExecutor

        executor = AlpacaExecutor()
        account = await executor.get_account()
        positions = await executor.get_positions()

        cash = float(account.get("cash", 0))
        equity = float(account.get("equity", 0))
        long_mv = float(account.get("long_market_value", 0))
        if long_mv <= 0 and positions:
            long_mv = sum(abs(float(p.get("market_value", 0))) for p in positions)

        trading = round(long_mv, 2)
        balance = round(cash, 2)
        total = round(equity if equity > 0 else trading + balance, 2)

        base = total if total > 0 else (trading + balance)
        max_position_usd = round(base * settings.MAX_POSITION_PCT / 100, 2)
        if settings.MAX_NOTIONAL_PER_POSITION_USD and settings.MAX_NOTIONAL_PER_POSITION_USD > 0:
            max_position_usd = round(min(max_position_usd, settings.MAX_NOTIONAL_PER_POSITION_USD), 2)

        return PortfolioMetricsOut(
            trading_usd=trading,
            balance_usd=balance,
            total_usd=total,
            mode="live",
            source="alpaca",
            open_maneuvers=0,
            active_grid_bots=0,
            as_of=datetime.now(timezone.utc).isoformat(),
            exposure_pct=round(trading / base * 100, 2) if base > 0 else 0.0,
            max_exposure_pct=settings.MAX_PORTFOLIO_EXPOSURE_PCT,
            cash_buffer_usd=round(base * settings.cash_buffer_pct / 100, 2),
            max_position_usd=max_position_usd,
            max_position_pct=settings.MAX_POSITION_PCT,
        )
    except Exception as exc:
        logger.warning("Alpaca portfolio metrics unavailable", error=str(exc))
        return None


async def _internal_metrics(
    email: str,
    db: AsyncSession,
    *,
    price_overrides: dict[str, float] | None = None,
) -> PortfolioMetricsOut:
    from app.services.portfolio.user_scope import get_user_by_email
    from app.services.portfolio.cap_limit import clamp_cap_to_balance

    stored_cap = await _user_portfolio_size(email)
    equity_base = await _user_paper_equity(email, db)
    user = await get_user_by_email(db, email)
    owner_user_id = user.id if user else None
    snapshot = await current_exposure(
        db,
        owner_user_id=owner_user_id,
        owner_email=email,
    )
    live = await compute_live_pnl(
        db,
        owner_user_id=owner_user_id,
        owner_email=email,
        price_overrides=price_overrides,
    )
    open_maneuvers = snapshot.open_maneuvers
    active_grids = snapshot.active_grid_bots
    deployed = snapshot.total_usd
    unrealized = live.unrealized_total_usd
    realized = live.realized_closed_usd

    # True paper equity never invents cash from an oversized notional.
    # (Previously total = trading+balance let deployed>$equity inflate BALANCE and CAP.)
    total = round(float(equity_base) + float(realized) + float(unrealized), 2)
    trading = round(float(deployed) + float(unrealized), 2)
    balance = round(max(0.0, total - trading), 2)
    deploy_cap = clamp_cap_to_balance(stored_cap, max(0.0, total))

    mode = "paper" if settings.PAPER_TRADING_ENABLED or not settings.live_trading_unlocked else "live"

    max_position_usd = round(deploy_cap * settings.MAX_POSITION_PCT / 100, 2)
    if settings.MAX_NOTIONAL_PER_POSITION_USD and settings.MAX_NOTIONAL_PER_POSITION_USD > 0:
        max_position_usd = round(min(max_position_usd, settings.MAX_NOTIONAL_PER_POSITION_USD), 2)
    cash_buffer_usd = round(deploy_cap * settings.cash_buffer_pct / 100, 2)
    exposure_pct = round(deployed / deploy_cap * 100, 2) if deploy_cap > 0 else 0.0

    out = PortfolioMetricsOut(
        trading_usd=trading,
        balance_usd=balance,
        total_usd=total,
        mode=mode,
        source="internal",
        open_maneuvers=open_maneuvers,
        active_grid_bots=active_grids,
        as_of=datetime.now(timezone.utc).isoformat(),
        exposure_pct=exposure_pct,
        max_exposure_pct=settings.MAX_PORTFOLIO_EXPOSURE_PCT,
        cash_buffer_usd=cash_buffer_usd,
        max_position_usd=max_position_usd,
        max_position_pct=settings.MAX_POSITION_PCT,
        unrealized_pnl_usd=unrealized,
        realized_pnl_usd=realized,
        deployed_notional_usd=deployed,
        portfolio_allocation_usd=deploy_cap,
    )
    return await _holdback_transient_flat_book(email, out)


async def _venue_account_totals(
    db: AsyncSession | None,
    *,
    user_id: str | None,
    account_mode: str,
) -> tuple[float | None, float | None]:
    """User vault keys only. Platform .env balances never appear here."""
    if account_mode != "live" or not user_id or db is None:
        return None, None
    try:
        from app.services.portfolio.user_venue_balances import build_user_venue_balances

        snapshot = await build_user_venue_balances(db, user_id)
        if not any(v.refreshed for v in snapshot.venues):
            return None, None
        return round(snapshot.total_balance_usd, 2), round(snapshot.total_usd, 2)
    except Exception as exc:  # noqa: BLE001
        logger.debug("user venue balance enrichment skipped", error=str(exc))
        return None, None


async def _attach_allocation_and_account(
    metrics: PortfolioMetricsOut,
    *,
    portfolio_allocation_usd: float,
    db: AsyncSession | None = None,
    user_id: str | None = None,
    account_mode: str = "paper",
) -> PortfolioMetricsOut:
    account_balance_usd, account_total_usd = await _venue_account_totals(
        db, user_id=user_id, account_mode=account_mode
    )
    from app.services.portfolio.cap_limit import clamp_cap_to_balance

    update: dict = {
        "portfolio_allocation_usd": round(portfolio_allocation_usd, 2),
        "account_balance_usd": account_balance_usd,
        "account_total_usd": account_total_usd,
        "mode": account_mode,
    }
    live_has_funds = (
        account_mode == "live"
        and account_total_usd is not None
        and float(account_total_usd) > 0
    )
    if live_has_funds:
        trading = float(metrics.trading_usd or 0.0)
        total = round(float(account_total_usd), 2)
        if account_balance_usd is not None:
            free = round(max(0.0, float(account_balance_usd)), 2)
        else:
            free = round(max(0.0, total - trading), 2)
        update["total_usd"] = total
        update["balance_usd"] = free
        update["portfolio_allocation_usd"] = clamp_cap_to_balance(
            float(portfolio_allocation_usd), total
        )
    elif account_mode == "live":
        # Live keys with an empty wallet are not a live account yet. Keep the
        # demo ledger for SUM/TRD/cap so paper trading still works. Exchange
        # sandbox keys are not required for this path.
        update["mode"] = "paper"
    return metrics.model_copy(update=update)


_FAST_METRICS_TTL_SEC = 5
_FAST_METRICS_KEY = "portfolio:fast_metrics:{email}"


async def _broker_view_metrics(db: AsyncSession, user_id: str) -> PortfolioMetricsOut:
    """The user's real broker account, for viewing (header switch on «Боевой»).

    Works with trading switched off: a read-only T-Bank or Finam token is enough.
    Numbers come only from the broker; nothing from the demo ledger is mixed in.
    """
    balance, total = await _venue_account_totals(db, user_id=user_id, account_mode="live")
    now = datetime.now(timezone.utc).isoformat()
    if total is None:
        return PortfolioMetricsOut(
            trading_usd=0.0, balance_usd=0.0, total_usd=0.0, mode="live",
            source="broker_unavailable", as_of=now,
        )
    free = round(max(0.0, float(balance if balance is not None else 0.0)), 2)
    in_positions = round(max(0.0, float(total) - free), 2)
    return PortfolioMetricsOut(
        trading_usd=in_positions,
        balance_usd=free,
        total_usd=round(float(total), 2),
        mode="live",
        source="broker",
        as_of=now,
        exposure_pct=round(in_positions / float(total) * 100, 2) if total else 0.0,
        deployed_notional_usd=in_positions,
        account_balance_usd=balance,
        account_total_usd=total,
        portfolio_allocation_usd=round(float(total), 2),
    )


async def build_portfolio_metrics(
    email: str,
    db: AsyncSession,
    *,
    price_overrides: dict[str, float] | None = None,
    view_mode: str | None = None,
) -> PortfolioMetricsOut:
    """Return live portfolio metrics; Alpaca only when live (not paper), else internal ledger.

    view_mode="live" (header switch) shows the connected broker account even when
    real trading is off; without a connected live broker it stays on the demo book.
    """
    from app.services.portfolio.user_scope import get_user_by_email
    from app.services.trading_keys.user_executor import resolve_user_account_mode, user_has_trading_key

    if view_mode == "live" and not price_overrides:
        # «Боевой» never shows the demo ledger: either the broker's own numbers,
        # or an empty account if no live broker key is connected.
        viewer = await get_user_by_email(db, email)
        if not viewer or not await user_has_trading_key(db, viewer.id, account_mode="live"):
            return PortfolioMetricsOut(
                trading_usd=0.0, balance_usd=0.0, total_usd=0.0, mode="live",
                source="no_live_broker", as_of=datetime.now(timezone.utc).isoformat(),
            )
        if await resolve_user_account_mode(db, viewer.id) != "live":
            return await _broker_view_metrics(db, viewer.id)

    cache_key = _FAST_METRICS_KEY.format(email=email.lower())
    if not price_overrides:
        cached = await cache_get(cache_key)
        if isinstance(cached, dict):
            try:
                return PortfolioMetricsOut.model_validate(cached)
            except Exception as exc:
                logger.warning("cached metrics invalid; recompute", error=str(exc)[:200])

    user = await get_user_by_email(db, email)
    account_mode = "paper"
    if user:
        account_mode = await resolve_user_account_mode(db, user.id)

    if account_mode == "live" and await _should_use_platform_alpaca_metrics(email):
        live = await _alpaca_metrics()
        if live is not None:
            portfolio_allocation = await _user_effective_deploy_cap(email, db)
            metrics = await _attach_allocation_and_account(
                live,
                portfolio_allocation_usd=portfolio_allocation,
                db=db,
                user_id=user.id if user else None,
                account_mode=account_mode,
            )
            if not price_overrides:
                await cache_set(cache_key, metrics.model_dump(mode="json"), ttl=_FAST_METRICS_TTL_SEC)
            return metrics
    internal = await _internal_metrics(email, db, price_overrides=price_overrides)
    metrics = await _attach_allocation_and_account(
        internal,
        portfolio_allocation_usd=internal.portfolio_allocation_usd,
        db=db,
        user_id=user.id if user else None,
        account_mode=account_mode,
    )
    if not price_overrides:
        await cache_set(cache_key, metrics.model_dump(mode="json"), ttl=_FAST_METRICS_TTL_SEC)
    return metrics


async def refresh_portfolio_metrics(email: str, db: AsyncSession) -> tuple[PortfolioMetricsOut, dict]:
    """Reconcile stale exposure locks, then return fresh portfolio metrics."""
    reconcile = await reconcile_stale_grid_exposure()
    metrics = await build_portfolio_metrics(email, db)
    # Refresh path must preserve live venue balance enrichment (same as GET /metrics).
    return metrics, reconcile
