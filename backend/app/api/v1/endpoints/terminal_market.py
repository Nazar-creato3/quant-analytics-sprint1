"""
Terminal Market aggregate API — Fincept-class panels without fake zeros.

Routes under /api/v1/terminal/:
  GET /snapshot       — full Market view payload
  GET /indices        — global indices panel
  GET /pulse          — market pulse
  GET /market-hours   — exchange sessions
  GET /tape           — running tape items
  GET /watchlist      — enriched watchlist (Dashboard parity+)
  GET /portfolio      — terminal portfolio block
  GET /quant/factors  — explanatory factor cards

Auth is optional: public market reads work without JWT; watchlist/portfolio
enrichment uses the caller identity when Authorization: Bearer is present.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.core.logging import get_logger
from app.core.security import JWTError, decode_token
from app.services.terminal_platform.market.factors import build_quant_factors
from app.services.terminal_platform.market.hours import build_market_hours
from app.services.terminal_platform.market.portfolio_block import build_portfolio_summary
from app.services.terminal_platform.market.pulse import build_pulse
from app.services.terminal_platform.market.quotes import fetch_indices
from app.services.terminal_platform.market.schemas import (
    MarketHoursRow,
    MarketPulseBlock,
    PortfolioSummaryBlock,
    QuantFactorRow,
    TapeItem,
    TerminalMarketSnapshot,
)
from app.services.terminal_platform.market.snapshot import build_terminal_snapshot
from app.services.terminal_platform.market.watchlist_enrich import build_enriched_watchlist

router = APIRouter(prefix="/terminal", tags=["terminal-market"])
logger = get_logger(__name__)
_optional_bearer = HTTPBearer(auto_error=False)


async def _optional_email(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_optional_bearer),
) -> Optional[str]:
    if credentials is None or not credentials.credentials:
        return None
    try:
        payload = decode_token(credentials.credentials)
        if payload.get("type") != "access":
            return None
        sub = payload.get("sub")
        return sub if isinstance(sub, str) and sub else None
    except JWTError:
        return None
    except Exception:
        return None


@router.get(
    "/snapshot",
    response_model=TerminalMarketSnapshot,
    summary="Terminal Market snapshot (indices, pulse, hours, tape, watchlist, portfolio, factors)",
)
async def terminal_snapshot(
    include_periods: bool = Query(
        False,
        description="Include week/month index % via batch yfinance (off by default for ≤30s paint)",
    ),
    wait: str = Query(
        "full",
        description="full = await enrichment under hard deadline; fast = shorter 10s budget",
    ),
    email: Optional[str] = Depends(_optional_email),
    db: AsyncSession = Depends(get_db),
) -> TerminalMarketSnapshot:
    # Soft-fail under hard deadline — OPEN/degraded providers must never hang the page.
    mode = (wait or "full").strip().lower()
    deadline_s = 10.0 if mode == "fast" else 26.0
    return await build_terminal_snapshot(
        db=db,
        email=email,
        include_periods=include_periods,
        deadline_s=deadline_s,
    )


@router.get("/indices", response_model=dict[str, Any])
async def terminal_indices(
    include_periods: bool = Query(False),
) -> dict[str, Any]:
    rows = await fetch_indices(include_periods=include_periods, deadline_s=14.0)
    return {
        "as_of": rows[0].as_of if rows and rows[0].as_of else None,
        "indices": [r.model_dump(mode="json") for r in rows],
        "ok_count": sum(1 for r in rows if r.status == "ok"),
        "no_data_count": sum(1 for r in rows if r.status == "no_data"),
    }


@router.get("/pulse", response_model=MarketPulseBlock)
async def terminal_pulse() -> MarketPulseBlock:
    return await build_pulse()


@router.get("/market-hours", response_model=list[MarketHoursRow])
async def terminal_market_hours() -> list[MarketHoursRow]:
    return build_market_hours()


@router.get("/tape", response_model=list[TapeItem])
async def terminal_tape(
    email: Optional[str] = Depends(_optional_email),
    db: AsyncSession = Depends(get_db),
) -> list[TapeItem]:
    # Lightweight path — do not rebuild full snapshot (that blocked Terminal).
    import asyncio

    from app.services.terminal_platform.market.coverage import build_tape_items
    from app.services.terminal_platform.market.news_fetch import fetch_terminal_news_multi

    async def _build() -> list[TapeItem]:
        indices, watchlist, hours, news = await asyncio.gather(
            fetch_indices(include_periods=False, deadline_s=5.0),
            build_enriched_watchlist(db, email, limit=12),
            asyncio.to_thread(build_market_hours),
            fetch_terminal_news_multi(limit=8),
        )
        pulse = await asyncio.wait_for(
            build_pulse(
                seed_quotes=[
                    {
                        "symbol": w.symbol,
                        "display": w.display,
                        "status": w.status,
                        "price": w.last,
                        "change_pct": w.change_pct,
                    }
                    for w in watchlist
                ]
            ),
            timeout=4.0,
        )
        return build_tape_items(
            indices=indices,
            watchlist=watchlist,
            pulse=pulse,
            hours=hours,
            news=news,
        )

    try:
        return await asyncio.wait_for(_build(), timeout=10.0)
    except Exception as exc:
        logger.warning("terminal tape soft-fail", error=str(exc))
        return []


@router.get("/watchlist", response_model=dict[str, Any])
async def terminal_watchlist(
    limit: int = Query(20, ge=1, le=50),
    email: Optional[str] = Depends(_optional_email),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows = await build_enriched_watchlist(db, email, limit=limit)
    return {
        "authenticated": bool(email),
        "items": [r.model_dump(mode="json") for r in rows],
        "ok_count": sum(1 for r in rows if r.status == "ok"),
        "no_data_count": sum(1 for r in rows if r.status == "no_data"),
    }


@router.get("/portfolio", response_model=PortfolioSummaryBlock)
async def terminal_portfolio(
    email: Optional[str] = Depends(_optional_email),
    db: AsyncSession = Depends(get_db),
) -> PortfolioSummaryBlock:
    return await build_portfolio_summary(db, email)


@router.get("/quant/factors", response_model=list[QuantFactorRow])
async def terminal_quant_factors(
    email: Optional[str] = Depends(_optional_email),
    db: AsyncSession = Depends(get_db),
) -> list[QuantFactorRow]:
    """Explanatory factors (also included in /snapshot)."""
    # Lightweight path: pulse + portfolio only (skip full index OHLCV periods).
    pulse = await build_pulse()
    portfolio = await build_portfolio_summary(db, email)
    index_pcts: dict[str, Optional[float]] = {}
    for g in pulse.global_snapshot:
        if g.key == "BTC" and g.change_pct is not None:
            index_pcts["BTC"] = g.change_pct
        if g.key == "VIX" and g.change_pct is not None:
            index_pcts["VIX"] = g.change_pct
    return build_quant_factors(pulse=pulse, portfolio=portfolio, index_change_pcts=index_pcts)
