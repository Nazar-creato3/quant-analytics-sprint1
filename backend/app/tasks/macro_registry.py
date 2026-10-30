"""Celery tasks for Macro Registry refresh (Prompt 47)."""
from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.tasks.async_runner import run_async
from app.tasks.celery_app import celery_app

logger = get_logger(__name__)


@celery_app.task(name="app.tasks.macro_registry.macro_daily_refresh_task")
def macro_daily_refresh_task() -> dict[str, Any]:
    return run_async(_async_macro_daily_refresh())


@celery_app.task(name="app.tasks.macro_registry.macro_weekly_report_task")
def macro_weekly_report_task() -> dict[str, Any]:
    return run_async(_async_macro_weekly_report())


@celery_app.task(name="app.tasks.macro_registry.macro_seed_registry_task")
def macro_seed_registry_task() -> dict[str, Any]:
    return run_async(_async_macro_seed())


@celery_app.task(name="app.tasks.macro_registry.macro_event_driven_refresh_task")
def macro_event_driven_refresh_task() -> dict[str, Any]:
    return run_async(_async_macro_event_driven_refresh())


@celery_app.task(name="app.tasks.macro_registry.compact_macro_storage_task")
def compact_macro_storage_task() -> dict[str, Any]:
    return run_async(_async_compact_macro_storage())


async def _async_macro_seed() -> dict[str, Any]:
    from app.db.session import AsyncSessionLocal
    from app.services.macro_registry.service import MacroRegistryService

    async with AsyncSessionLocal() as session:
        service = MacroRegistryService()
        seeded = await service.seed_registry(session)
        migrated = await service.migrate_legacy_indicators(session)
        return {"seeded": seeded, "migrated": migrated}


async def _async_macro_daily_refresh() -> dict[str, Any]:
    from app.db.session import AsyncSessionLocal
    from app.services.macro_registry.scheduler import MacroRefreshScheduler
    from app.services.macro_registry.service import MacroRegistryService

    scheduler = MacroRefreshScheduler()
    service = MacroRegistryService()
    async with AsyncSessionLocal() as session:
        return await scheduler.run_daily_refresh(session, service)


async def _async_macro_weekly_report() -> dict[str, Any]:
    from app.db.session import AsyncSessionLocal
    from app.services.macro_registry.report_engine import MacroReportEngine
    from app.services.macro_registry.scheduler import MacroRefreshScheduler
    from app.services.macro_registry.storage import MacroStorageLayer

    scheduler = MacroRefreshScheduler()
    engine = MacroReportEngine()
    storage = MacroStorageLayer()
    async with AsyncSessionLocal() as session:
        result = await scheduler.run_weekly_deep_report(session, engine, storage)
        archived = await storage.archive_old_report_snapshots(session, weeks=12)
        await session.commit()
        result["archived_snapshots"] = archived
        return result


async def _async_macro_event_driven_refresh() -> dict[str, Any]:
    from app.db.session import AsyncSessionLocal
    from app.services.macro_registry.scheduler import MacroRefreshScheduler
    from app.services.macro_registry.service import MacroRegistryService

    scheduler = MacroRefreshScheduler()
    service = MacroRegistryService()
    async with AsyncSessionLocal() as session:
        return await scheduler.run_event_driven_refresh(session, service)


async def _async_compact_macro_storage() -> dict[str, Any]:
    from app.db.session import AsyncSessionLocal
    from app.services.macro_registry.storage import MacroStorageLayer

    storage = MacroStorageLayer()
    async with AsyncSessionLocal() as session:
        archived = await storage.archive_old_report_snapshots(session, weeks=12)
        compacted = await storage.compact_raw_responses(session, retention_years=2)
        await session.commit()
        return {"archived_snapshots": archived, **compacted}
