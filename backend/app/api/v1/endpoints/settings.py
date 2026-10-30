"""
User settings API.
Stores per-user overrides in Redis; Postgres watchlist is the durable fallback.
Syncs watchlist to Postgres and instruments registry for pipeline/news/forecast.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.config import settings
from app.core.deps import get_current_user_email, get_db
from app.core.logging import get_logger
from app.schemas.schemas import UserSettingsOut, UserSettingsUpdate
from app.services.settings.watchlist import get_effective_watchlist, sync_default_watchlist
from app.utils.audit import AuditAction, audit
from app.utils.cache import cache_get, cache_set
from app.utils.helpers import get_user_settings_key

logger = get_logger(__name__)
router = APIRouter(prefix="/settings", tags=["settings"])

SETTINGS_TTL = 60 * 60 * 24 * 365  # 1 year


def _defaults() -> dict:
    return {
        "portfolio_size": settings.DEFAULT_PORTFOLIO_SIZE,
        "max_risk_per_trade_pct": settings.MAX_RISK_PER_TRADE_PCT,
        "confidence_threshold": settings.NO_TRADE_CONFIDENCE_THRESHOLD,
        "daily_max_loss_pct": settings.DAILY_MAX_LOSS_PCT,
        "default_watchlist": settings.default_watchlist_list,
        "paper_trading_enabled": settings.PAPER_TRADING_ENABLED,
        "live_trading_enabled": settings.live_trading_unlocked,
        "tokenized_equity_provider": "bybit",
    }


@router.get("", response_model=UserSettingsOut)
async def get_settings(
    email: str = Depends(get_current_user_email),
    db=Depends(get_db),
) -> UserSettingsOut:
    key = get_user_settings_key(email)
    stored = await cache_get(key) or {}
    merged = {**_defaults(), **stored}
    # Always reconcile watchlist from durable sources (Redis → DB → env).
    merged["default_watchlist"] = await get_effective_watchlist(db, email)
    from app.services.portfolio.metrics import user_account_total_usd

    cap_max = await user_account_total_usd(email, db)
    return UserSettingsOut(**merged, cap_max_usd=cap_max)


@router.put("", response_model=UserSettingsOut)
async def update_settings(
    body: UserSettingsUpdate,
    email: str = Depends(get_current_user_email),
    db=Depends(get_db),
) -> UserSettingsOut:
    key = get_user_settings_key(email)
    current = await cache_get(key) or {}
    updates = body.model_dump(exclude_none=True)
    if updates.get("tokenized_equity_provider") == "mexc":
        updates["tokenized_equity_provider"] = "bybit"

    if "portfolio_size" in updates:
        from app.services.portfolio.cap_limit import cap_exceeds_balance
        from app.services.portfolio.metrics import user_account_total_usd

        cap_max = await user_account_total_usd(email, db)
        requested = float(updates["portfolio_size"])
        if cap_exceeds_balance(requested, cap_max):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Кап не может быть больше баланса на счетах "
                    f"(${cap_max:,.2f}). Это доля имеющихся денег, не отдельный депозит."
                ),
            )

    merged = {**_defaults(), **current, **updates}

    if updates.get("default_watchlist") is not None:
        from app.services.market_data.moex_spot import normalize_watchlist_ticker

        normalized = [normalize_watchlist_ticker(t) for t in updates["default_watchlist"] if t.strip()]
        await sync_default_watchlist(db, email, normalized)
        merged["default_watchlist"] = normalized

    persisted = await cache_set(key, merged, ttl=SETTINGS_TTL)
    if not persisted:
        logger.warning("Settings cache write failed — watchlist still persisted to DB", user=email)

    await audit.log(
        db,
        action=AuditAction.SETTINGS_CHANGED,
        resource_type="settings",
        details={"fields": list(updates.keys()), "user": email},
    )
    logger.info("Settings updated", user=email, fields=list(updates.keys()))
    from app.services.portfolio.metrics import user_account_total_usd

    cap_max = await user_account_total_usd(email, db)
    return UserSettingsOut(**merged, cap_max_usd=cap_max)

