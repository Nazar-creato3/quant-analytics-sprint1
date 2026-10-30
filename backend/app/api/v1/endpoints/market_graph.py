"""Market graph query API (Prompt 20)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access_deps import require_ops_read
from app.core.deps import get_current_user_email, get_db
from app.schemas.market_graph import (
    CorrelatedClusterOut,
    MarketGraphRebuildOut,
    SectorContextOut,
)
from app.services.market_graph import MarketGraph

router = APIRouter(prefix="/market-graph", tags=["market-graph"])
_service = MarketGraph()


@router.get("/cluster/{instrument_id}", response_model=CorrelatedClusterOut)
async def get_correlated_cluster(
    instrument_id: int,
    threshold: float = Query(0.7, ge=0.0, le=1.0),
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> CorrelatedClusterOut:
    """Return correlated instrument cluster for RiskGate read-model."""
    cluster = await _service.get_correlated_cluster(db, instrument_id, threshold)
    return CorrelatedClusterOut(
        instrument_id=instrument_id,
        threshold=threshold,
        cluster_instrument_ids=cluster,
    )


@router.get("/sector-context/{instrument_id}", response_model=SectorContextOut)
async def get_sector_context(
    instrument_id: int,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> SectorContextOut:
    """Return aggregate sector metrics for an instrument."""
    context = await _service.get_sector_context(db, instrument_id)
    if context is None:
        raise HTTPException(
            status_code=404,
            detail="Для этой бумаги секторный контекст пока недоступен.",
        )
    return SectorContextOut(
        instrument_id=context.instrument_id,
        sector=context.sector,
        peer_instrument_ids=list(context.peer_instrument_ids),
        peer_count=context.peer_count,
        average_intra_sector_correlation=context.average_intra_sector_correlation,
        factor_exposure_summary=context.factor_exposure_summary,
        updated_at=context.updated_at,
    )


@router.post("/rebuild", response_model=MarketGraphRebuildOut)
async def rebuild_market_graph(
    force: bool = Query(False),
    _: object = Depends(require_ops_read),
    db: AsyncSession = Depends(get_db),
) -> MarketGraphRebuildOut:
    """Rebuild graph edges from DB sources."""
    counts = await _service.rebuild(db, force=force)
    return MarketGraphRebuildOut(counts=counts)
