"""Effective watchlist resolution — merges user settings with DB watchlists."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import User, Watchlist
from app.services.market_data.moex_spot import normalize_watchlist_ticker
from app.utils.cache import cache_get
from app.utils.helpers import get_user_settings_key


async def _user_watchlist_from_db(db: AsyncSession, email: str) -> list[str] | None:
    """Load the operator's persisted watchlist from Postgres."""
    user_result = await db.execute(select(User).where(User.email == email.lower()))
    user = user_result.scalar_one_or_none()
    if user is not None:
        result = await db.execute(
            select(Watchlist)
            .where(Watchlist.owner_id == user.id)
            .order_by(Watchlist.updated_at.desc())
            .limit(1)
        )
        owned = result.scalar_one_or_none()
        if owned and owned.tickers:
            return [normalize_watchlist_ticker(t) for t in owned.tickers if t.strip()]
        # A registered user without a list of their own gets the configured
        # default (Russian market first), not whatever list was last saved as
        # the shared default — that row held an old US-only list.
        return None

    result = await db.execute(
        select(Watchlist)
        .where(Watchlist.is_default.is_(True))
        .order_by(Watchlist.updated_at.desc())
        .limit(1)
    )
    default_wl = result.scalar_one_or_none()
    if default_wl and default_wl.tickers:
        return [normalize_watchlist_ticker(t) for t in default_wl.tickers if t.strip()]
    return None


async def get_effective_watchlist(
    db: AsyncSession | None = None,
    email: str | None = None,
) -> list[str]:
    """Return the operator watchlist: user Redis settings → user DB watchlist → default DB → env."""
    tickers: list[str] = []

    if email:
        stored = await cache_get(get_user_settings_key(email))
        if stored and stored.get("default_watchlist"):
            tickers = [normalize_watchlist_ticker(t) for t in stored["default_watchlist"] if t.strip()]

    if not tickers and db is not None:
        db_tickers = await _user_watchlist_from_db(db, email) if email else None
        if db_tickers:
            tickers = db_tickers
        elif email is None:
            result = await db.execute(
                select(Watchlist)
                .where(Watchlist.is_default.is_(True))
                .order_by(Watchlist.updated_at.desc())
                .limit(1)
            )
            default_wl = result.scalar_one_or_none()
            if default_wl and default_wl.tickers:
                tickers = [normalize_watchlist_ticker(t) for t in default_wl.tickers if t.strip()]

    if not tickers:
        tickers = list(settings.default_watchlist_list)

    # Preserve order, dedupe
    seen: set[str] = set()
    ordered: list[str] = []
    for t in tickers:
        if t not in seen:
            seen.add(t)
            ordered.append(t)
    return ordered


async def get_effective_watchlist_enriched(
    db: AsyncSession | None = None,
    email: str | None = None,
) -> list[dict[str, str | None]]:
    """Return watchlist symbols with auto-detected category labels."""
    from app.services.instrument.category import enrich_watchlist_entry

    symbols = await get_effective_watchlist(db, email)
    entries = [enrich_watchlist_entry(symbol) for symbol in symbols]
    # Russian market first (product is for Russian investors); order inside each group kept.
    return sorted(entries, key=lambda e: 0 if str(e.get("market") or "").startswith("moex") else 1)


async def sync_default_watchlist(
    db: AsyncSession,
    email: str,
    tickers: list[str],
) -> None:
    """Persist watchlist to Postgres (user-owned + default) and ensure instrument rows."""
    normalized = [normalize_watchlist_ticker(t) for t in tickers if t.strip()]

    user_result = await db.execute(select(User).where(User.email == email.lower()))
    user = user_result.scalar_one_or_none()
    if user is not None:
        result = await db.execute(
            select(Watchlist).where(Watchlist.owner_id == user.id).limit(1)
        )
        owned = result.scalar_one_or_none()
        if owned is None:
            owned = Watchlist(
                name="My Watchlist",
                tickers=normalized,
                owner_id=user.id,
                is_default=False,
            )
            db.add(owned)
        else:
            owned.tickers = normalized

    from app.services.instrument.resolver import ensure_instruments_for_symbols

    await ensure_instruments_for_symbols(db, normalized)
    await db.commit()


async def pin_watchlist_symbol(db: AsyncSession, email: str, symbol: str) -> list[str]:
    """Append a symbol to the operator watchlist (idempotent)."""
    from app.utils.cache import cache_get, cache_set
    from app.utils.helpers import get_user_settings_key

    normalized = normalize_watchlist_ticker(symbol)
    tickers = await get_effective_watchlist(db, email)
    if normalized not in tickers:
        tickers = [*tickers, normalized]
    await sync_default_watchlist(db, email, tickers)
    key = get_user_settings_key(email)
    stored = await cache_get(key) or {}
    stored["default_watchlist"] = tickers
    await cache_set(key, stored, ttl=60 * 60 * 24 * 365)
    return tickers


async def unpin_watchlist_symbol(db: AsyncSession, email: str, symbol: str) -> list[str]:
    """Remove a symbol from the operator watchlist."""
    from app.utils.cache import cache_get, cache_set
    from app.utils.helpers import get_user_settings_key

    normalized = normalize_watchlist_ticker(symbol)
    tickers = [t for t in await get_effective_watchlist(db, email) if t != normalized]
    await sync_default_watchlist(db, email, tickers)
    key = get_user_settings_key(email)
    stored = await cache_get(key) or {}
    stored["default_watchlist"] = tickers
    await cache_set(key, stored, ttl=60 * 60 * 24 * 365)
    return tickers
