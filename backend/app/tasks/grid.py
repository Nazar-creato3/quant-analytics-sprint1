"""Grid bot Celery tasks — automatic paper-mode price ticks."""
from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.tasks.async_runner import run_async
from app.tasks.celery_app import celery_app

logger = get_logger(__name__)


@celery_app.task(name="app.tasks.grid.tick_grid_bots_task")
def tick_grid_bots_task() -> dict[str, Any]:
    """Fetch live quotes and simulate fills for all active grid bots."""
    from app.core.config import settings
    from app.utils.healthchecks import ping_healthcheck

    try:
        result = run_async(_async_tick_grid_bots())
        ping_healthcheck(settings.HC_PING_GRIDBOT, success=result.get("status") not in ("failed", "halted"))
        return result
    except Exception as exc:
        logger.exception("Grid bot tick failed", error=str(exc))
        ping_healthcheck(settings.HC_PING_GRIDBOT, success=False)
        return {"status": "failed", "reason": str(exc), "updated": 0, "fills": 0}


async def _async_tick_grid_bots() -> dict[str, Any]:
    from app.api.v1.endpoints.grid import _GRID_KEY, _load_all_bots, _save_all_bots
    from app.services.control_fabric.strategy_halt import check_strategy_halt_async
    from app.services.grid.tick import apply_price_tick
    from app.services.market_data.client import get_grid_tick_quote
    from app.services.market_data.quote_utils import extract_quote_price

    halt = await check_strategy_halt_async()
    if halt.halted:
        logger.warning("Grid tick skipped — kill switch active", reason=halt.reason, source=halt.source)
        return {"status": "halted", "reason": halt.reason, "updated": 0, "fills": 0}

    from app.api.v1.endpoints.dca_bots import _DCA_KEY, _memory_bots as dca_memory
    from app.api.v1.endpoints.momentum_bots import _MOMENTUM_KEY, _memory_bots as mom_memory
    from app.services.bot_risk.guard import (
        build_snapshot_from_stores,
        load_peak_pnl,
        run_portfolio_circuit_breaker,
    )
    from app.services.bots.store import load_bots, save_bots

    dca_bots = await load_bots(_DCA_KEY, dca_memory)
    mom_bots = await load_bots(_MOMENTUM_KEY, mom_memory)
    bots = await _load_all_bots()

    cb = await run_portfolio_circuit_breaker(grid=bots, dca=dca_bots, momentum=mom_bots)
    if cb and cb.tripped:
        await _save_all_bots(bots)
        await save_bots(_DCA_KEY, dca_memory, dca_bots)
        await save_bots(_MOMENTUM_KEY, mom_memory, mom_bots)
        return {
            "status": "circuit_breaker",
            "reason": cb.reason,
            "drawdown_pct": cb.drawdown_pct,
            "updated": 0,
            "fills": 0,
        }

    if not bots:
        return {"status": "ok", "updated": 0, "fills": 0}

    peak = await load_peak_pnl()
    risk_snapshot = build_snapshot_from_stores(
        grid=bots, dca=dca_bots, momentum=mom_bots, peak_pnl=peak
    )

    updated = 0
    total_fills = 0

    for bot_id, data in list(bots.items()):
        if not data.get("is_active", True):
            continue
        if data.get("is_paused"):
            continue
        ticker = data.get("config", {}).get("ticker", "")
        if not ticker:
            continue

        trades_before = data.get("total_trades", 0)
        price = 0.0
        try:
            quote = await get_grid_tick_quote(ticker.upper())
            resolved = extract_quote_price(quote)
            if resolved is not None:
                price = resolved
        except Exception as exc:
            logger.warning("Grid tick quote unavailable", ticker=ticker, error=str(exc))

        if price <= 0:
            logger.warning("Grid tick skipped — no price", ticker=ticker, bot_id=bot_id)
            continue

        bots[bot_id] = apply_price_tick(
            data, price, bot_id=bot_id, risk_snapshot=risk_snapshot
        )
        updated += 1
        total_fills += bots[bot_id].get("total_trades", 0) - trades_before

        # Audit circuit breaker pause/resume events
        for ev in bots[bot_id].get("recent_events") or []:
            if ev.get("type") == "circuit_breaker":
                try:
                    from app.db.session import AsyncSessionLocal
                    from app.utils.audit import AuditAction, audit

                    async with AsyncSessionLocal() as session:
                        await audit.log(
                            session,
                            action=AuditAction.PIPELINE_TRIGGERED,
                            details={
                                "event": "grid_circuit_breaker",
                                "bot_id": bot_id,
                                "message": ev.get("message"),
                                "price": ev.get("price"),
                            },
                        )
                        await session.commit()
                except Exception:
                    raise
                break

    if updated:
        await _save_all_bots(bots)

    result = {"status": "ok", "updated": updated, "fills": total_fills}
    try:
        from datetime import datetime, timezone

        from app.utils.cache import cache_set

        await cache_set(
            "ops:grid_bot_last_tick",
            {**result, "ts_utc": datetime.now(timezone.utc).isoformat()},
            ttl=3600,
        )
    except Exception:
        raise

    logger.info("Grid bot tick complete", updated=updated, new_fills=total_fills)
    return result
