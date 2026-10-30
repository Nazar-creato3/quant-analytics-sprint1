"""Celery ticks for standalone DCA and momentum bots."""
from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.tasks.async_runner import run_async
from app.tasks.celery_app import celery_app

logger = get_logger(__name__)


@celery_app.task(name="app.tasks.strategy_bots.tick_strategy_bots_task")
def tick_strategy_bots_task() -> dict[str, Any]:
    try:
        return run_async(_async_tick_strategy_bots())
    except Exception as exc:
        logger.exception("Strategy bot tick failed", error=str(exc))
        return {"status": "failed", "reason": str(exc), "updated": 0}


async def _async_tick_strategy_bots() -> dict[str, Any]:
    from app.api.v1.endpoints.dca_bots import _DCA_KEY, _memory_bots as dca_memory
    from app.api.v1.endpoints.momentum_bots import _MOMENTUM_KEY, _memory_bots as mom_memory
    from app.services.bots.dca import apply_dca_tick
    from app.services.bots.momentum import apply_momentum_tick
    from app.services.bots.store import load_bots, save_bots
    from app.services.control_fabric.strategy_halt import check_strategy_halt_async
    from app.services.market_data.client import get_grid_tick_quote
    from app.services.market_data.quote_utils import extract_quote_price

    from app.api.v1.endpoints.grid import _GRID_KEY, _load_all_bots, _save_all_bots
    from app.services.bot_risk.guard import (
        build_snapshot_from_stores,
        load_peak_pnl,
        run_portfolio_circuit_breaker,
    )

    halt = await check_strategy_halt_async()
    if halt.halted:
        return {"status": "halted", "reason": halt.reason, "updated": 0}

    grid_bots = await _load_all_bots()
    dca_bots = await load_bots(_DCA_KEY, dca_memory)
    mom_bots = await load_bots(_MOMENTUM_KEY, mom_memory)

    cb = await run_portfolio_circuit_breaker(
        grid=grid_bots, dca=dca_bots, momentum=mom_bots
    )
    if cb and cb.tripped:
        await _save_all_bots(grid_bots)
        await save_bots(_DCA_KEY, dca_memory, dca_bots)
        await save_bots(_MOMENTUM_KEY, mom_memory, mom_bots)
        return {
            "status": "circuit_breaker",
            "reason": cb.reason,
            "drawdown_pct": cb.drawdown_pct,
            "updated": 0,
        }

    peak = await load_peak_pnl()
    risk_snapshot = build_snapshot_from_stores(
        grid=grid_bots, dca=dca_bots, momentum=mom_bots, peak_pnl=peak
    )

    updated = 0

    async def _tick_store(
        redis_key: str,
        memory: dict[str, dict],
        apply_fn,
    ) -> int:
        nonlocal updated
        bots = await load_bots(redis_key, memory)
        changed = False
        for bot_id, data in list(bots.items()):
            if not data.get("is_active", True) or data.get("is_paused"):
                continue
            ticker = (data.get("config") or {}).get("ticker", "")
            if not ticker:
                continue
            price = 0.0
            try:
                quote = await get_grid_tick_quote(ticker.upper())
                resolved = extract_quote_price(quote)
                if resolved is not None:
                    price = resolved
            except Exception as exc:
                logger.debug("Strategy bot quote failed", ticker=ticker, error=str(exc))
            if price <= 0:
                logger.info("strategy bot tick skipped: no quote", ticker=ticker, bot_id=bot_id)
                continue
            bots[bot_id] = apply_fn(
                data, price, bot_id=bot_id, risk_snapshot=risk_snapshot
            )
            changed = True
            updated += 1
        if changed:
            await save_bots(redis_key, memory, bots)
        return updated

    await _tick_store(_DCA_KEY, dca_memory, apply_dca_tick)
    await _tick_store(_MOMENTUM_KEY, mom_memory, apply_momentum_tick)
    return {"status": "ok", "updated": updated}
