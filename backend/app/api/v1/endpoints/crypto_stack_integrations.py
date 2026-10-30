"""Crypto-stack third_party integrations API."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.core.access_deps import require_ops_read
from app.core.deps import require_admin
from app.core.logging import get_logger
from app.services.crypto_stack.integrations import (
    INTEGRATION_NAMES,
    get_integration,
    list_integrations,
)

router = APIRouter(prefix="/crypto-stack/integrations", tags=["crypto-stack-integrations"])
logger = get_logger(__name__)

_PROXY_ALLOWED = {
    "crypto-analytics-platform",
    "opentao-api",
    "celebrum-ai-go",
}


class IntegrationActionBody(BaseModel):
    """Optional JSON body for actions that need lists (e.g. Fincept push_watchlist)."""

    kind: str | None = None
    symbols: list[str] | None = None
    tickers: list[str] | None = None
    path: str | None = None
    ticker: str | None = None
    lamports: int | None = None
    script: str | None = None
    limit: int | None = Field(default=None, ge=1, le=200)


def _require(name: str):
    adapter = get_integration(name)
    if adapter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "unknown_integration",
                "name": name,
                "known": list(INTEGRATION_NAMES),
            },
        )
    return adapter


@router.get("")
@router.get("/")
async def integrations_list(
    _: dict = Depends(require_admin),
) -> dict:
    """List all integrations (admin / owner only). Fincept removed — use /terminal Companion."""
    items = list_integrations()
    return {
        "ok": True,
        "count": len(items),
        "expected": list(INTEGRATION_NAMES),
        "items": items,
    }


@router.get("/{name}/status")
async def integration_status(
    name: str,
    _: object = Depends(require_ops_read),
) -> dict:
    adapter = _require(name)
    return adapter.status()


@router.get("/{name}/capabilities")
async def integration_capabilities(
    name: str,
    _: object = Depends(require_ops_read),
) -> dict:
    adapter = _require(name)
    return adapter.capabilities()


@router.post("/{name}/action")
async def integration_action(
    name: str,
    kind: str | None = Query(None, description="Action kind override"),
    ticker: str | None = Query(None),
    path: str | None = Query(None, description="Proxy path for sidecar actions"),
    lamports: int | None = Query(None),
    script: str | None = Query(None),
    symbols: str | None = Query(
        None, description="Comma-separated symbols (Fincept push_watchlist)"
    ),
    body: IntegrationActionBody | None = Body(default=None),
    _: dict = Depends(require_admin),
) -> dict:
    """Run a safe probe/sample action; fails gracefully if deps missing."""
    adapter = _require(name)
    kwargs: dict[str, Any] = {}
    if body:
        if body.kind:
            kwargs["kind"] = body.kind
        if body.ticker:
            kwargs["ticker"] = body.ticker
        if body.path:
            kwargs["path"] = body.path
        if body.lamports is not None:
            kwargs["lamports"] = body.lamports
        if body.script:
            kwargs["script"] = body.script
        if body.limit is not None:
            kwargs["limit"] = body.limit
        if body.symbols:
            kwargs["symbols"] = body.symbols
        elif body.tickers:
            kwargs["symbols"] = body.tickers
    if kind:
        kwargs["kind"] = kind
    if ticker:
        kwargs["ticker"] = ticker
    if path:
        kwargs["path"] = path
    if lamports is not None:
        kwargs["lamports"] = lamports
    if script:
        kwargs["script"] = script
    if symbols and "symbols" not in kwargs:
        kwargs["symbols"] = [s.strip() for s in symbols.split(",") if s.strip()]
    try:
        result = adapter.action(**kwargs)
    except Exception as exc:  # noqa: BLE001
        logger.warning("integration action failed", name=name, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"action_failed: {type(exc).__name__}",
        ) from exc
    return result


@router.get("/{name}/proxy")
async def integration_proxy(
    name: str,
    path: str = Query("health", description="Path on the sidecar (no leading host)"),
    _: dict = Depends(require_admin),
) -> dict:
    """HTTP proxy to Docker/Go sidecars when they expose a base URL."""
    if name not in _PROXY_ALLOWED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "proxy_not_supported",
                "name": name,
                "allowed": sorted(_PROXY_ALLOWED),
            },
        )
    adapter = _require(name)
    proxy_fn = getattr(adapter, "proxy", None)
    if proxy_fn is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="proxy_not_implemented",
        )
    # Block path traversal / absolute URLs
    clean = path.lstrip("/")
    if ".." in clean or clean.startswith("http"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_path")
    try:
        return proxy_fn(clean)
    except Exception as exc:  # noqa: BLE001
        logger.warning("integration proxy failed", name=name, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"proxy_failed: {type(exc).__name__}",
        ) from exc
