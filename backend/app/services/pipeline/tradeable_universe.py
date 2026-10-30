"""Resolve the analysis universe: tradeable market for this user, not only pins."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.services.pipeline.market_regime import REGIME_ANCHORS

logger = get_logger(__name__)

# Full ML/news pass — wide enough to pick the best names, small enough for the worker.
ANALYSIS_CAP = 42
CRYPTO_HINTS = ("-USD", "USDT", "BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA")


@dataclass
class AnalysisUniverse:
    tickers: list[str]
    pins: list[str] = field(default_factory=list)
    screen: list[str] = field(default_factory=list)
    venues: list[str] = field(default_factory=list)
    source: str = "liquid+digest"


def _norm(raw: str | None) -> str:
    return str(raw or "").strip().upper()


def _liquid_symbols() -> list[str]:
    from app.services.market_data.market_overview import LIQUID_UNIVERSE

    return [_norm(sym) for sym, _, _ in LIQUID_UNIVERSE if _norm(sym)]


def _board_symbols() -> list[str]:
    from app.services.market_data.equity_eod_store import board_symbols

    return [_norm(s) for s in board_symbols() if _norm(s)]


def _looks_crypto(sym: str) -> bool:
    u = _norm(sym)
    return any(h in u for h in CRYPTO_HINTS) or u.endswith("USDT")


def _digest_screen(digest: dict[str, Any] | None) -> list[str]:
    if not isinstance(digest, dict):
        return []
    out: list[str] = []
    for key in ("screen_top", "top_movers"):
        rows = digest.get(key) or []
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, dict):
                sym = _norm(row.get("symbol") or row.get("ticker"))
            else:
                sym = _norm(str(row))
            if sym and sym not in out:
                out.append(sym)
    return out


async def _user_venues(db: AsyncSession | None, user_id: str | None) -> list[str]:
    if not db or not user_id:
        return []
    found: list[str] = []
    try:
        from app.services.trading_keys.user_executor import user_has_trading_key

        for venue in ("alpaca", "bybit", "binance", "tinkoff", "mexc"):
            try:
                if await user_has_trading_key(db, user_id, venue=venue):
                    found.append(venue)
            except Exception:
                continue
    except Exception as exc:
        logger.debug("universe_venues_failed", error=str(exc)[:120])
    return found


def _filter_for_venues(tickers: list[str], venues: list[str]) -> list[str]:
    """Keep names the connected stack can actually route. Paper / no keys → US+liquid."""
    if not venues:
        return tickers
    crypto_only = set(venues).issubset({"bybit", "binance", "mexc"})
    ru_only = set(venues) == {"tinkoff"}
    if crypto_only:
        kept = [t for t in tickers if _looks_crypto(t)]
        return kept or tickers
    if ru_only:
        return tickers
    return tickers


def merge_analysis_tickers(
    *,
    pins: list[str],
    digest: dict[str, Any] | None,
    venues: list[str] | None = None,
    cap: int = ANALYSIS_CAP,
) -> list[str]:
    screen = _digest_screen(digest)
    liquid = _liquid_symbols()
    board = _board_symbols()
    pin_norm = [_norm(p) for p in pins if _norm(p)]

    ordered: list[str] = []
    for bucket in (REGIME_ANCHORS, screen, liquid, board, pin_norm):
        for sym in bucket:
            s = _norm(sym)
            if s and s not in ordered:
                ordered.append(s)

    filtered = _filter_for_venues(ordered, venues or [])
    # Always keep anchors + pins even after venue filter.
    must = [_norm(s) for s in list(REGIME_ANCHORS) + pin_norm if _norm(s)]
    final: list[str] = []
    for s in must + filtered:
        if s not in final:
            final.append(s)
        if len(final) >= cap:
            break
    return final


async def resolve_analysis_universe(
    db: AsyncSession | None,
    *,
    owner_user_id: str | None,
    pins: list[str],
    digest: dict[str, Any] | None,
    cap: int = ANALYSIS_CAP,
) -> AnalysisUniverse:
    venues = await _user_venues(db, owner_user_id)
    tickers = merge_analysis_tickers(pins=pins, digest=digest, venues=venues, cap=cap)
    return AnalysisUniverse(
        tickers=tickers,
        pins=[_norm(p) for p in pins if _norm(p)],
        screen=_digest_screen(digest)[:cap],
        venues=venues,
        source="digest+liquid+board+pins" if digest else "liquid+board+pins",
    )
