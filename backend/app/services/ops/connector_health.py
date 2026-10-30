"""Per-connector health aggregation for ops dashboard."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.macro_registry import MacroSourceRegistryORM
from app.utils.alert_webhook import emit_alert_webhook
from app.utils.cache import cache_get, cache_set

CONNECTOR_IDS = (
    "binance",
    "tinkoff",
    "moex",
    "coinglass",
    "fred",
    "cbr",
    "news",
    "macro_adapters",
    "twenty_crm",
)

FAILURE_ALERT_THRESHOLD = 3
CACHE_KEY_PREFIX = "ops:connector:"


class ConnectorHealthRow(BaseModel):
    connector_id: str
    last_success_at: str | None = None
    consecutive_failures: int = 0
    status: str = "unknown"
    detail: str | None = None


async def record_connector_success(connector_id: str, *, detail: str | None = None) -> None:
    payload = {
        "last_success_at": datetime.now(timezone.utc).isoformat(),
        "consecutive_failures": 0,
        "status": "ok",
        "detail": detail,
    }
    await cache_set(f"{CACHE_KEY_PREFIX}{connector_id}", payload, ttl=86400 * 7)


async def record_connector_failure(connector_id: str, *, detail: str | None = None) -> None:
    key = f"{CACHE_KEY_PREFIX}{connector_id}"
    prev = await cache_get(key) or {}
    failures = int(prev.get("consecutive_failures") or 0) + 1
    payload = {
        "last_success_at": prev.get("last_success_at"),
        "consecutive_failures": failures,
        "status": "degraded" if failures < FAILURE_ALERT_THRESHOLD else "down",
        "detail": detail,
    }
    await cache_set(key, payload, ttl=86400 * 7)
    if failures >= FAILURE_ALERT_THRESHOLD:
        await emit_alert_webhook(
            f"Connector health alert: {connector_id}",
            {"connector": connector_id, "consecutive_failures": failures, "detail": detail or ""},
        )


async def _macro_adapter_health(db: AsyncSession) -> ConnectorHealthRow:
    try:
        result = await db.execute(select(MacroSourceRegistryORM))
        rows = list(result.scalars().all())
        if not rows:
            return ConnectorHealthRow(
                connector_id="macro_adapters",
                status="unknown",
                detail="No macro sources registered",
            )
        stale = 0
        latest: datetime | None = None
        now = datetime.now(timezone.utc)
        for row in rows:
            ts = row.last_successful_refresh
            if ts is None:
                stale += 1
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if latest is None or ts > latest:
                latest = ts
            if (now - ts).total_seconds() > 86400 * 2:
                stale += 1
        status = "ok" if stale == 0 else ("degraded" if stale < len(rows) else "down")
        return ConnectorHealthRow(
            connector_id="macro_adapters",
            last_success_at=latest.isoformat() if latest else None,
            consecutive_failures=stale,
            status=status,
            detail=f"{len(rows)} sources, {stale} stale/missing",
        )
    except Exception as exc:
        return ConnectorHealthRow(
            connector_id="macro_adapters",
            status="unknown",
            detail=str(exc),
        )


async def build_connector_health(db: AsyncSession) -> dict[str, Any]:
    items: list[ConnectorHealthRow] = []

    for connector_id in CONNECTOR_IDS:
        if connector_id == "macro_adapters":
            items.append(await _macro_adapter_health(db))
            continue

        cached = await cache_get(f"{CACHE_KEY_PREFIX}{connector_id}")
        if cached:
            items.append(
                ConnectorHealthRow(
                    connector_id=connector_id,
                    last_success_at=cached.get("last_success_at"),
                    consecutive_failures=int(cached.get("consecutive_failures") or 0),
                    status=str(cached.get("status") or "unknown"),
                    detail=cached.get("detail"),
                )
            )
            continue

        # Seed from environment presence when no runtime telemetry yet.
        detail = "No fetch telemetry yet"
        status = "unknown"
        import os

        if connector_id == "binance":
            has_key = bool(os.getenv("BINANCE_API_KEY") or os.getenv("BINANCE_API_SECRET"))
            status = "ok" if has_key else "degraded"
            detail = "API key present" if has_key else "Missing BINANCE_API_KEY"
        elif connector_id == "tinkoff":
            has_key = bool(os.getenv("TINKOFF_API_TOKEN") or os.getenv("TINKOFF_TOKEN"))
            status = "ok" if has_key else "unknown"
            detail = "Market data token configured; orders use user tokens" if has_key else "Token not configured"
        elif connector_id == "moex":
            status = "ok"
            detail = "MOEX ISS public endpoint"
        elif connector_id in ("fred", "cbr"):
            status = "ok"
            detail = "Macro registry adapter"
        elif connector_id == "coinglass":
            has_key = bool(os.getenv("COINGLASS_API_KEY"))
            status = "ok" if has_key else "degraded"
            detail = "Coinglass API key configured" if has_key else "Optional key missing"
        elif connector_id == "news":
            status = "ok"
            detail = "News aggregator task"
        elif connector_id == "twenty_crm":
            from app.core.config import settings as app_settings

            configured = bool(
                app_settings.TWENTY_API_URL.strip() and app_settings.TWENTY_API_KEY.strip()
            )
            status = "ok" if configured else "degraded"
            detail = "Twenty CRM API configured" if configured else "TWENTY_API_URL/KEY not set"

        items.append(
            ConnectorHealthRow(
                connector_id=connector_id,
                status=status,
                detail=detail,
            )
        )

    down = [i.connector_id for i in items if i.status == "down"]
    return {
        "items": [i.model_dump() for i in items],
        "summary": {
            "total": len(items),
            "down": len(down),
            "down_connectors": down,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        },
    }
