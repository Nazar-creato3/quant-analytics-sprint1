"""Universe construction without dead names: listing freshness + ADV."""
from __future__ import annotations

from typing import Any, Mapping

from app.services.pit.clock import as_day, add_days


DEFAULT_MAX_STALE_DAYS = 10
DEFAULT_MIN_ADV_USD = 1_000_000.0


def is_listed_as_of(
    *,
    last_bar_date: Any,
    as_of: Any,
    listing_end: Any = None,
    max_stale_days: int = DEFAULT_MAX_STALE_DAYS,
) -> bool:
    """True if the name still printed on or shortly before as_of and was not delisted."""
    as_of_day = as_day(as_of)
    last = as_day(last_bar_date)
    if not as_of_day or not last or last > as_of_day:
        return False
    ended = as_day(listing_end)
    if ended and ended < as_of_day:
        return False
    cutoff = add_days(as_of_day, -max(0, int(max_stale_days)))
    return last >= cutoff


def passes_liquidity(adv_usd: float | None, *, min_adv_usd: float = DEFAULT_MIN_ADV_USD) -> bool:
    try:
        adv = float(adv_usd or 0.0)
    except (TypeError, ValueError):
        return False
    return adv >= float(min_adv_usd)


def construct_universe(
    rows: list[Mapping[str, Any]],
    *,
    as_of: Any,
    min_adv_usd: float = DEFAULT_MIN_ADV_USD,
    max_stale_days: int = DEFAULT_MAX_STALE_DAYS,
) -> list[str]:
    """Keep liquid, still-listed names. Corporate-action/delist end date wins over last bar."""
    kept: list[str] = []
    seen: set[str] = set()
    for row in rows:
        sym = str(row.get("symbol") or row.get("ticker") or "").strip().upper()
        if not sym or sym in seen:
            continue
        if not is_listed_as_of(
            last_bar_date=row.get("last_bar_date") or row.get("last_date"),
            as_of=as_of,
            listing_end=row.get("listing_end") or row.get("delisted_on"),
            max_stale_days=max_stale_days,
        ):
            continue
        if not passes_liquidity(row.get("adv_usd") or row.get("dollar_volume"), min_adv_usd=min_adv_usd):
            continue
        seen.add(sym)
        kept.append(sym)
    return kept


def stooq_row_to_universe_member(
    symbol: str,
    last_bar_date: Any,
    *,
    close: float | None = None,
    volume: float | None = None,
) -> dict[str, Any]:
    px = float(close or 0.0)
    vol = float(volume or 0.0)
    return {
        "symbol": str(symbol).upper(),
        "last_bar_date": as_day(last_bar_date),
        "adv_usd": px * vol if px > 0 and vol > 0 else 0.0,
        "source": "stooq",
    }


def member_from_bars(
    symbol: str,
    bars: list[Mapping[str, Any]],
    *,
    as_of: Any,
    adv_window: int = 21,
) -> dict[str, Any] | None:
    """Last print ≤ as_of. ADV = mean dollar volume of the last window. Future bars dropped."""
    cap = as_day(as_of)
    known = [b for b in bars if as_day(b.get("date") or b.get("Date")) and as_day(b.get("date") or b.get("Date")) <= cap]
    if not known:
        return None
    last = known[-1]
    window = known[-max(1, int(adv_window)) :]
    notionals: list[float] = []
    for b in window:
        try:
            c = float(b.get("close") or 0.0)
            v = float(b.get("volume") or 0.0)
        except (TypeError, ValueError):
            continue
        if c > 0 and v > 0:
            notionals.append(c * v)
    adv = sum(notionals) / len(notionals) if notionals else 0.0
    last_day = as_day(last.get("date") or last.get("Date"))
    listing_end = last_day if last_day < cap else None
    return {
        "symbol": str(symbol).upper(),
        "last_bar_date": last_day,
        "listing_end": listing_end if listing_end and listing_end < add_days(cap, -DEFAULT_MAX_STALE_DAYS) else None,
        "adv_usd": adv,
        "source": "stooq",
    }


def apply_edgar_listing(
    symbols: list[str],
    *,
    as_of: Any,
    edgar_tickers: set[str] | None,
    today: Any,
) -> list[str]:
    """Today's EDGAR map is only legal on today. Using it on a past as_of is survivorship bias."""
    if not edgar_tickers:
        return symbols
    if as_day(as_of) != as_day(today):
        return symbols
    listed = {str(s).strip().upper() for s in edgar_tickers}
    return [s for s in symbols if s in listed or "." in s or "-" in s]


def universe_from_stooq_members(
    members: list[Mapping[str, Any]],
    *,
    as_of: Any,
    edgar_tickers: set[str] | None = None,
    today: Any = None,
    min_adv_usd: float = DEFAULT_MIN_ADV_USD,
    max_stale_days: int = DEFAULT_MAX_STALE_DAYS,
) -> list[str]:
    names = construct_universe(
        members,
        as_of=as_of,
        min_adv_usd=min_adv_usd,
        max_stale_days=max_stale_days,
    )
    return apply_edgar_listing(names, as_of=as_of, edgar_tickers=edgar_tickers, today=today)
