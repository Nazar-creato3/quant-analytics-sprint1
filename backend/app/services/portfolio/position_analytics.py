"""
Per-position analytics for the Positions tab / chart panel.

For each maneuver we expose these enrichment fields consumed by the frontend:
  * current_price   — latest known close (live P&L reference), from local OHLCV DB
  * approx_profit   — projected NET P&L if the take-profit is hit, after fees
  * unrealized_pnl  — live NET P&L if the position were closed at current_price
  * time_to_close   — estimated seconds until the trade likely closes

``approx_profit`` is the *full* net P&L if take-profit is hit (after fees) — not
the model's expected outcome on the remaining horizon. Use ``tp_hit_probability``
and ``expected_pnl_low``/``high`` (from profit projection) for honest expectations.

Everything is computed from data already in the DB (no per-request network
calls) so the list endpoint stays fast.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import Maneuver, OHLCVBar
from app.utils.json_safe import finite_float

logger = get_logger(__name__)

_SECONDS = {
    "minute": 60,
    "hour": 3600,
    "day": 86_400,
    "week": 604_800,
    "month": 2_592_000,  # ~30d
}

# DB OHLCV close older than this triggers a live quote overlay (equities).
STALE_BAR_SECONDS = 900  # 15 minutes


# Russian/English horizon unit keywords -> canonical bucket.
_UNIT_PATTERNS = [
    (re.compile(r"минут|minute|\bмин\b", re.I), "minute"),
    (re.compile(r"час|hour|\bч\b|ч\.", re.I), "hour"),
    (re.compile(r"недел|week|\bнед\b", re.I), "week"),
    (re.compile(r"меся|month|\bмес\b", re.I), "month"),
    (re.compile(r"дн|day|день|дня|дней", re.I), "day"),
]


_PHRASE_SECONDS: list[tuple[re.Pattern[str], int]] = [
    (re.compile(r"внутри.?дня|до закрытия|сессия", re.I), 6 * 3600),
    (re.compile(r"минут", re.I), 45 * 60),
    (re.compile(r"^час$|час\b", re.I), 3600),
]


def horizon_to_seconds(time_horizon: str | None) -> int | None:
    """Parse a fuzzy horizon like '3–10 дней' / '1-3 дня' into midpoint seconds."""
    if not time_horizon:
        return None
    text = time_horizon.replace("–", "-").replace("—", "-").strip()
    if re.search(r"не для", text, re.I):
        return None
    nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", text)]
    if not nums:
        for pattern, seconds in _PHRASE_SECONDS:
            if pattern.search(text):
                return seconds
        return None
    midpoint = sum(nums) / len(nums)

    unit = "day"
    for pattern, bucket in _UNIT_PATTERNS:
        if pattern.search(text):
            unit = bucket
            break
    return int(midpoint * _SECONDS[unit])


def maneuver_stop_loss(m: Maneuver) -> float | None:
    """JSON-safe stop; fall back to invalidation when DB holds NaN/null."""
    sl = finite_float(m.stop_loss)
    if sl is not None:
        return sl
    return finite_float(m.invalidation_level)


def maneuver_take_profit(m: Maneuver) -> float | None:
    """JSON-safe take-profit; fall back to exit zone when DB holds NaN/null."""
    tp = finite_float(m.take_profit)
    if tp is not None:
        return tp
    high = finite_float(m.exit_zone_high)
    low = finite_float(m.exit_zone_low)
    if high is not None and low is not None:
        return (high + low) / 2.0
    return high or low


def display_sl_tp_fallback(
    m: Maneuver,
    *,
    interval_forecast: object | None = None,
) -> tuple[float | None, float | None]:
    """Volatility-proxy SL/TP for API display when DB columns are missing/NaN."""
    sl = maneuver_stop_loss(m)
    tp = maneuver_take_profit(m)
    if sl is not None and tp is not None:
        return sl, tp
    entry = _entry_reference(m)
    if entry is None or entry <= 0:
        return sl, tp
    from app.services.risk.profit_projection import _infer_daily_vol

    daily_vol = None
    if interval_forecast is not None and getattr(interval_forecast, "rolling_volatility", 0) > 0:
        daily_vol = float(interval_forecast.rolling_volatility)
    vol = _infer_daily_vol(entry, sl, daily_vol)
    dist = max(vol * 2.0 * entry, entry * 0.005)
    is_short = str(m.direction).lower() == "short"
    if sl is None:
        sl = entry + dist if is_short else entry - dist
    if tp is None:
        tp = entry - 2.0 * dist if is_short else entry + 2.0 * dist
    return round(sl, 4), round(tp, 4)


def _entry_reference(m: Maneuver) -> float | None:
    fill = finite_float(m.fill_price)
    if fill is not None and fill > 0:
        return fill
    entry_col = finite_float(getattr(m, "entry_price", None))
    if entry_col is not None and entry_col > 0:
        return entry_col
    low = finite_float(m.entry_zone_low)
    high = finite_float(m.entry_zone_high)
    if low is not None and high is not None:
        return (low + high) / 2.0
    if high is not None:
        return high
    if low is not None:
        return low
    meta = getattr(m, "signal_meta", None) or {}
    if isinstance(meta, dict):
        for key in ("signal_price", "generated_price", "reference_price", "entry_price"):
            val = finite_float(meta.get(key))
            if val is not None and val > 0:
                return val
    return None


def _direction_sign(m: Maneuver) -> float:
    return -1.0 if str(m.direction).lower() == "short" else 1.0


def position_quantity(m: Maneuver) -> float | None:
    """Share/contract quantity implied by the USD notional and entry price."""
    entry = _entry_reference(m)
    size = float(m.position_size_usd or 0.0)
    if entry is None or entry <= 0 or size <= 0:
        return None
    return size / entry


def _round_trip_fees(m: Maneuver) -> float:
    """Estimated entry+exit commission on the position notional."""
    size = float(m.position_size_usd or 0.0)
    return size * (settings.COMMISSION_RATE_PCT / 100.0) * 2.0


def _net_pnl_at(m: Maneuver, exit_price: float) -> float | None:
    """NET P&L (USD) if the position were closed at ``exit_price``, after fees.

    LONG:  (exit - entry) * qty - fees
    SHORT: (entry - exit) * qty - fees   (handled via the direction sign)
    """
    entry = _entry_reference(m)
    qty = position_quantity(m)
    if entry is None or qty is None:
        return None
    gross = (float(exit_price) - entry) * qty * _direction_sign(m)
    return round(gross - _round_trip_fees(m), 2)


def approx_net_profit(m: Maneuver) -> float | None:
    """Projected NET P&L if the take-profit is hit, after round-trip fees."""
    tp = maneuver_take_profit(m)
    if tp is None:
        return None
    return _net_pnl_at(m, tp)


def unrealized_net_pnl(m: Maneuver, current_price: float | None) -> float | None:
    """Live NET P&L if the position were closed *now* at ``current_price``."""
    if current_price is None or current_price <= 0:
        return None
    return _net_pnl_at(m, float(current_price))


def _filled_at_utc(m: Maneuver) -> datetime | None:
    if m.filled_at is None:
        return None
    filled = m.filled_at
    if filled.tzinfo is None:
        return filled.replace(tzinfo=timezone.utc)
    return filled


def _utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _explicit_expiry_at(m: Maneuver) -> datetime | None:
    """User-selected exact expiry stored in signal_meta wins over derived horizons."""
    meta = getattr(m, "signal_meta", None) or {}
    if not isinstance(meta, dict):
        return None
    raw = meta.get("expiry_at") or meta.get("horizon_end_at")
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        parsed = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return _utc(parsed)


def _horizon_anchor_at(m: Maneuver) -> datetime | None:
    """Stable anchor for countdown identity; never use request time as the anchor."""
    return (
        _filled_at_utc(m)
        or _utc(getattr(m, "approved_at", None))
        or _utc(getattr(m, "created_at", None))
    )


def expiry_anchor_at(m: Maneuver) -> datetime:
    """UTC anchor for computing a *new* relative expiry (approve/edit/fill).

    Must not use pipeline ``created_at`` — maneuvers can sit pending for hours
    before approval, which would shrink the horizon and cause immediate
    expiration on fill.
    """
    return (
        _filled_at_utc(m)
        or _utc(getattr(m, "approved_at", None))
        or datetime.now(timezone.utc)
    )


def apply_horizon_expiry_overrides(
    maneuver: Maneuver,
    *,
    time_horizon: str | None = None,
    expiry_at: datetime | None = None,
) -> dict[str, str]:
    """Persist user-controlled duration; returns changed fields for audit."""
    changes: dict[str, str] = {}
    if time_horizon is not None and time_horizon.strip():
        maneuver.time_horizon = time_horizon.strip()
        changes["time_horizon"] = maneuver.time_horizon

    meta = dict(getattr(maneuver, "signal_meta", None) or {})

    if expiry_at is not None:
        expiry = expiry_at if expiry_at.tzinfo else expiry_at.replace(tzinfo=timezone.utc)
        meta["expiry_at"] = expiry.isoformat()
        meta["expiry_source"] = "absolute"
        maneuver.signal_meta = meta
        changes["expiry_at"] = meta["expiry_at"]
        changes["expiry_source"] = "absolute"
    elif time_horizon is not None and time_horizon.strip():
        secs = horizon_to_seconds(time_horizon.strip())
        anchor = expiry_anchor_at(maneuver)
        if secs is not None:
            computed = anchor + timedelta(seconds=secs)
            meta["expiry_at"] = computed.isoformat()
            meta["expiry_source"] = "relative"
            meta["expiry_anchor"] = "filled_at" if _filled_at_utc(maneuver) else "approve_or_now"
            maneuver.signal_meta = meta
            changes["expiry_at"] = meta["expiry_at"]
            changes["expiry_source"] = "relative"
    return changes


def reanchor_relative_expiry_on_fill(maneuver: Maneuver) -> bool:
    """After fill, start relative horizons from ``filled_at`` (not pipeline ``created_at``)."""
    meta = dict(getattr(maneuver, "signal_meta", None) or {})
    if meta.get("expiry_source") == "absolute":
        return False
    filled = _filled_at_utc(maneuver)
    if filled is None:
        return False
    secs = horizon_to_seconds(maneuver.time_horizon)
    if secs is None:
        return False
    meta["expiry_at"] = (filled + timedelta(seconds=secs)).isoformat()
    meta["expiry_source"] = "relative"
    meta["expiry_anchor"] = "filled_at"
    maneuver.signal_meta = meta
    return True


def horizon_end_at(m: Maneuver, now: datetime | None = None) -> datetime | None:
    """Absolute UTC expiry instant for the maneuver horizon (server-trusted)."""
    explicit = _explicit_expiry_at(m)
    if explicit is not None:
        return explicit
    horizon = horizon_to_seconds(m.time_horizon)
    if horizon is None:
        return None
    anchor = _horizon_anchor_at(m)
    if anchor is None:
        return None
    return anchor + timedelta(seconds=horizon)


def time_to_close_seconds(m: Maneuver, now: datetime | None = None) -> int | None:
    """Remaining seconds until the stated horizon expires (0 if overdue)."""
    end = horizon_end_at(m, now)
    if end is None:
        return None
    now = now or datetime.now(timezone.utc)
    return int(max(0, (end - now).total_seconds()))


def _status_token(m: Maneuver) -> str:
    status = getattr(m, "status", None)
    raw = status.value if hasattr(status, "value") else status
    return str(raw or "").strip().lower()


OPEN_BOOK_STATUS_TOKENS = frozenset({"approved", "executing", "filled"})


def horizon_expired(m: Maneuver, now: datetime | None = None) -> bool:
    """True when the stated horizon is overdue (filled or still waiting for a fill)."""
    ttc = time_to_close_seconds(m, now)
    return ttc is not None and ttc <= 0


def should_auto_close_on_horizon(m: Maneuver, now: datetime | None = None) -> bool:
    """Open-book rows whose horizon elapsed must become CLOSED for audit."""
    if _status_token(m) not in OPEN_BOOK_STATUS_TOKENS:
        return False
    return horizon_expired(m, now)


async def latest_prices(db: AsyncSession, tickers: list[str]) -> dict[str, float]:
    """Latest close per ticker — DB OHLCV with live overlay when bars are stale."""
    uniq = sorted({t.upper() for t in tickers if t})
    if not uniq:
        return {}

    now = datetime.now(timezone.utc)

    # Newest timestamp per ticker, then join back to grab that close.
    sub = (
        select(OHLCVBar.ticker, func.max(OHLCVBar.timestamp).label("ts"))
        .where(OHLCVBar.ticker.in_(uniq))
        .group_by(OHLCVBar.ticker)
        .subquery()
    )
    stmt = select(OHLCVBar.ticker, OHLCVBar.close, OHLCVBar.timestamp).join(
        sub, (OHLCVBar.ticker == sub.c.ticker) & (OHLCVBar.timestamp == sub.c.ts)
    )
    result = await db.execute(stmt)
    prices: dict[str, float] = {}
    bar_ts: dict[str, datetime] = {}
    for ticker, close, ts in result.all():
        px = finite_float(close)
        if px is not None and px > 0:
            prices[ticker] = px
            if ts is not None:
                bar_ts[ticker] = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)

    # Overlay Binance live spot for crypto — DB daily close can lag hours behind.
    try:
        from app.services.market_data.binance_spot import get_crypto_quotes_batch, is_crypto_ticker

        crypto = [t for t in uniq if is_crypto_ticker(t)]
        if crypto:
            live = await get_crypto_quotes_batch(crypto)
            prices.update(live)
    except Exception as exc:
        logger.warning("Crypto live price overlay failed", error=str(exc))

    # Live overlay for missing tickers AND equities with stale DB bars.
    needs_live: list[str] = []
    for ticker in uniq:
        if ticker not in prices:
            needs_live.append(ticker)
            continue
        ts = bar_ts.get(ticker)
        if ts is not None:
            age = (now - ts).total_seconds()
            if age > STALE_BAR_SECONDS:
                needs_live.append(ticker)
                logger.debug(
                    "Stale DB bar — scheduling live overlay",
                    ticker=ticker,
                    bar_age_sec=int(age),
                )

    stale = [t for t in uniq if t in prices and not finite_float(prices[t])]
    for ticker in stale:
        prices.pop(ticker, None)
    needs_live = sorted(set(needs_live) | set(stale))

    if needs_live:
        from app.services.market_data.client import get_latest_quote_resolved
        from app.services.market_data.quote_utils import extract_quote_price

        async def _resolve_one(ticker: str) -> tuple[str, float | None]:
            try:
                quote = await get_latest_quote_resolved(ticker)
                px = extract_quote_price(quote)
                if px is not None and px > 0:
                    logger.debug("Live quote overlay applied", ticker=ticker, price=px)
                return ticker, px
            except Exception as exc:
                logger.warning(
                    "Live quote overlay failed for ticker",
                    ticker=ticker,
                    error=str(exc),
                )
                return ticker, None

        resolved = await asyncio.gather(*(_resolve_one(t) for t in needs_live))
        for ticker, px in resolved:
            if px is not None and px > 0:
                prices[ticker] = float(px)

    return prices


async def enrich_maneuvers(
    db: AsyncSession, maneuvers: list[Maneuver]
) -> dict[str, dict[str, float | int | bool | str | None]]:
    """Return live position analytics keyed by maneuver id."""
    if not maneuvers:
        return {}
    from app.services.risk.profit_projection import compute_profit_projection, horizon_to_days

    prices = await latest_prices(db, [m.ticker for m in maneuvers])
    interval_by_ticker: dict[str, object | None] = {}
    try:
        from app.services.risk.hierarchy_intervals import load_intervals_for_tickers

        interval_by_ticker = await load_intervals_for_tickers(
            db,
            [m.ticker for m in maneuvers],
            use_orchestrator=False,
        )
    except Exception as exc:
        logger.debug("Interval overlay for enrich_maneuvers skipped", error=str(exc))

    now = datetime.now(timezone.utc)

    out: dict[str, dict[str, float | int | bool | str | None]] = {}
    for m in maneuvers:
        price = prices.get(m.ticker.upper())
        entry = _entry_reference(m)
        fees = _round_trip_fees(m)
        horizon_days = horizon_to_days(m.time_horizon)
        remaining_days: float | None = None
        if horizon_days is not None:
            elapsed_days = 0.0
            if m.filled_at is not None:
                filled = m.filled_at
                if filled.tzinfo is None:
                    filled = filled.replace(tzinfo=timezone.utc)
                elapsed_days = (now - filled).total_seconds() / 86_400.0
            remaining_days = max(0.0, horizon_days - elapsed_days)

        interval = interval_by_ticker.get(m.ticker.upper())
        disp_sl, disp_tp = display_sl_tp_fallback(m, interval_forecast=interval)
        eff_sl = maneuver_stop_loss(m) or disp_sl
        eff_tp = maneuver_take_profit(m) or disp_tp

        projection = None
        if entry and m.position_size_usd:
            sign = -1 if str(m.direction).lower() == "short" else 1
            projection = compute_profit_projection(
                direction=str(m.direction),
                entry_price=entry,
                take_profit=eff_tp,
                stop_loss=eff_sl,
                position_size_usd=float(m.position_size_usd),
                time_horizon=m.time_horizon,
                round_trip_fees_usd=fees,
                remaining_days=remaining_days,
                interval_forecast=interval,
                momentum_sign=sign if m.confidence and m.confidence >= 0.55 else 0,
            )

        approx = approx_net_profit(m)
        if approx is None and eff_tp is not None:
            approx = _net_pnl_at(m, eff_tp)

        end_at = horizon_end_at(m, now)
        row: dict[str, float | int | bool | str | None] = {
            "current_price": finite_float(price),
            "approx_profit": approx,
            "unrealized_pnl": unrealized_net_pnl(m, finite_float(price)),
            "time_to_close": time_to_close_seconds(m, now),
            "horizon_end_at": end_at.isoformat() if end_at is not None else None,
            "horizon_expired": horizon_expired(m, now),
        }
        unrealized = row["unrealized_pnl"]
        if isinstance(unrealized, (int, float)):
            from app.services.portfolio.entry_snapshot import update_peak_unrealized

            update_peak_unrealized(m, float(unrealized))
        if disp_sl is not None:
            row["display_stop_loss"] = disp_sl
        if disp_tp is not None:
            row["display_take_profit"] = disp_tp
        if projection:
            row["tp_hit_probability"] = projection.tp_hit_probability
            row["profit_disclosure"] = projection.disclosure_ru
            row["expected_pnl_low"] = projection.expected_pnl_low
            row["expected_pnl_high"] = projection.expected_pnl_high
            row["expected_return_low"] = projection.expected_return_low_pct
            row["expected_return_high"] = projection.expected_return_high_pct
        out[m.id] = row
    logger.info(
        "live_positions_enriched",
        count=len(out),
        tickers=sorted({m.ticker for m in maneuvers}),
        as_of=now.isoformat(),
    )
    return out
