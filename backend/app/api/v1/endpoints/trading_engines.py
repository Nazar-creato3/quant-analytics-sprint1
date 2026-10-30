"""Trading engines API — GitHub repo integrations health + probes."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.core.access_deps import require_ops_read
from app.core.deps import require_admin
from app.core.logging import get_logger
from app.services.trading_engines.health import engines_health
from app.services.trading_engines.registry import ENGINE_NAMES, get_engine

router = APIRouter(prefix="/trading-engines", tags=["trading-engines"])
logger = get_logger(__name__)


class EngineActionBody(BaseModel):
    kind: str | None = None
    exchange: str | None = None
    symbol: str | None = None
    payload: dict[str, Any] | None = None
    prices: list[float] | None = None
    candidates: list[dict[str, Any]] | None = None
    limit: int | None = Field(default=None, ge=1, le=200)
    mid: float | None = None
    capital: float | None = None
    timeframe: str | None = None
    lookback: int | None = Field(default=None, ge=2, le=200)
    risk_level: str | None = None
    episodes: int | None = Field(default=None, ge=4, le=80)


def _require(name: str):
    adapter = get_engine(name)
    if adapter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "unknown_engine", "name": name, "known": list(ENGINE_NAMES)},
        )
    return adapter


@router.get("/health")
async def trading_engines_health(
    github_check: bool = Query(False, description="Fetch GitHub repo metadata (uses GITHUB_TOKEN)"),
    _: object = Depends(require_ops_read),
) -> dict:
    """Health for 8 trading-engine repos + MCP probes."""
    import asyncio

    # Blocking probes: run off the event loop so other users' requests are not held.
    return await asyncio.to_thread(engines_health, github_check=github_check)


@router.get("")
@router.get("/")
async def trading_engines_list(
    _: dict = Depends(require_admin),
) -> dict:
    """List all trading engines with status (admin)."""
    import asyncio

    payload = await asyncio.to_thread(engines_health, github_check=False)
    return {
        "ok": payload.get("ok"),
        "count": payload.get("engine_count"),
        "expected": list(ENGINE_NAMES),
        "items": payload.get("engines", []),
        "mcp": payload.get("mcp"),
        "alpaca_data": payload.get("alpaca_data"),
    }


@router.get("/alpaca/data-status")
async def alpaca_data_status_route(
    _: object = Depends(require_ops_read),
) -> dict:
    from app.services.trading_engines.runtime.alpaca_data import alpaca_data_status

    return alpaca_data_status()


@router.get("/{name}/status")
async def engine_status(
    name: str,
    _: object = Depends(require_ops_read),
) -> dict:
    return _require(name).status()


@router.get("/{name}/capabilities")
async def engine_capabilities(
    name: str,
    _: object = Depends(require_ops_read),
) -> dict:
    return _require(name).capabilities()


@router.post("/{name}/action")
async def engine_action(
    name: str,
    kind: str | None = Query(None),
    body: EngineActionBody | None = None,
    _: dict = Depends(require_admin),
) -> dict:
    adapter = _require(name)
    kwargs: dict[str, Any] = {}
    if body:
        kwargs.update(body.model_dump(exclude_none=True))
    if kind:
        kwargs["kind"] = kind
    try:
        return adapter.action(**kwargs)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="нет данных")
    except Exception as exc:  # noqa: BLE001
        logger.warning("engine action failed", name=name, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="нет данных",
        ) from exc
