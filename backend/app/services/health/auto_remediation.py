"""Auto-remediation for whitelisted health-check failures."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

_HUMAN_ESCALATION_TESTS = frozenset(
    {
        "test_no_cross_user_position_leak",
        "test_chat_no_raw_debug_output",
        "test_no_duplicate_positions_across_accounts",
        "cross_user_position_isolation",
        "auth_login",
    }
)

_JOB_TASKS = {
    "data_ingestion": "app.tasks.data_ingestion.ingest_market_data_task",
    "forecast": "app.tasks.forecast.refresh_daily_forecasts_task",
    "gridbot": "app.tasks.grid.tick_grid_bots_task",
    "news": "app.tasks.data_ingestion.ingest_news_task",
}


async def _log_remediation(action: str, details: dict[str, Any]) -> None:
    try:
        from app.db.session import AsyncSessionLocal
        from app.utils.audit import AuditAction, audit

        async with AsyncSessionLocal() as session:
            await audit.log(
                session,
                action=AuditAction.PIPELINE_TRIGGERED,
                resource_type="auto_remediation",
                details={"event": action, **details, "ts": datetime.now(timezone.utc).isoformat()},
            )
            await session.commit()
    except Exception as exc:
        logger.warning("auto_remediation_audit_failed", error=str(exc))


async def remediate_websocket_dead() -> bool:
    try:
        from app.utils.cache import cache_delete_pattern

        await cache_delete_pattern("live:binance:*")
        await cache_delete_pattern("terminal:*")
        await _log_remediation("ws_auto_reconnect", {"reason": "no_message_15s", "action": "cache_invalidate"})
        return True
    except Exception as exc:
        logger.warning("ws_auto_reconnect_failed", error=str(exc))
        return False


async def remediate_job_failure(job_key: str) -> bool:
    task_name = _JOB_TASKS.get(job_key)
    if not task_name:
        return False
    await asyncio.sleep(60)
    try:
        from app.tasks.celery_app import celery_app

        celery_app.send_task(task_name)
        await _log_remediation("job_auto_retry", {"job": job_key, "task": task_name})
        return True
    except Exception as exc:
        logger.warning("job_auto_retry_failed", job=job_key, error=str(exc))
        return False


async def remediate_terminal_news_stale() -> bool:
    """Refresh in-process terminal news cache (health check reads /terminal/news, not DB ingest)."""
    try:
        from app.services.terminal_platform.market.news_fetch import fetch_terminal_news_multi

        rows = await fetch_terminal_news_multi(limit=20, force_refresh=True)
        await _log_remediation(
            "terminal_news_force_refresh",
            {"headlines": len(rows or []), "action": "force_refresh"},
        )
        return bool(rows)
    except Exception as exc:
        logger.warning("terminal_news_force_refresh_failed", error=str(exc))
        return False


async def remediate_stale_cache(cache_key: str) -> bool:
    try:
        from app.utils.cache import cache_delete
    except Exception as exc:
        logger.warning("cache_auto_refetch_skip", error=str(exc))
        return False

    ticker = cache_key.split(":")[-1] if ":" in cache_key else "SPY"
    ticker = ticker.upper()
    for key in {cache_key, f"quotes:{ticker}", f"quote:equity:{ticker}"}:
        await cache_delete(key)
    try:
        from app.db.session import AsyncSessionLocal
        from app.services.market_data.bars import get_bars_for_chart
        from app.services.market_data.client import get_latest_quote_resolved

        async with AsyncSessionLocal() as session:
            await get_bars_for_chart(session, ticker, "1d", 5, force_refresh=True)
        await get_latest_quote_resolved(ticker, force_refresh=True)
        await _log_remediation("cache_auto_refetch", {"cache_key": cache_key, "ticker": ticker})
        return True
    except Exception as exc:
        logger.warning("cache_auto_refetch_failed", key=cache_key, error=str(exc))
        return False


async def apply_remediations(results: list[dict[str, Any]]) -> list[str]:
    actions: list[str] = []
    for row in results:
        name = row.get("name", "")
        if row.get("status") != "failed":
            continue
        if name in _HUMAN_ESCALATION_TESTS:
            continue
        err = (row.get("error") or "").lower()
        if name == "test_websocket_delivers_message" or "websocket" in err:
            if await remediate_websocket_dead():
                actions.append("ws_reconnect")
        elif "ingestion" in err or "forecast" in err or "grid" in err:
            for key in _JOB_TASKS:
                if key.replace("_", "") in err.replace("_", "") or key in err:
                    if await remediate_job_failure(key):
                        actions.append(f"job_retry:{key}")
                    break
        elif name == "news_feed_freshness" or (name == "news_feed_freshness" and "stale" in err):
            if await remediate_terminal_news_stale():
                actions.append("terminal_news_refresh")
            elif await remediate_job_failure("news"):
                actions.append("job_retry:news")
        elif "stale" in err or "cache" in err or name == "market_data_freshness":
            key = row.get("cache_key") or "quotes:SPY"
            if await remediate_stale_cache(key):
                actions.append(f"cache_refetch:{key}")
    return actions
