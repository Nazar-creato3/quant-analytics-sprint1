"""Public catalog resolve API (Prompt 03)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.services.catalog import resolve
from app.services.qa.feature_flags import is_enabled
from app.services.qa.session_user import require_session_user_id

router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.get("/resolve")
def catalog_resolve(
    q: str = Query(..., min_length=1, max_length=64),
    _user_id: str = Depends(require_session_user_id),
) -> dict:
    if not is_enabled("qa_catalog"):
        raise HTTPException(status_code=404, detail="нет данных")
    try:
        hit = resolve(q)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="нет данных") from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="нет данных") from exc
    return {
        "query": hit.query,
        "symbol": hit.symbol,
        "asset_id": hit.asset_id,
        "instrument_kind": hit.instrument_kind,
        "venue": hit.venue,
        "listings": list(hit.listings),
        "candidates": list(hit.candidates),
        "ambiguous": hit.ambiguous,
        "tradeable": hit.tradeable,
        "trade_block_reason": hit.trade_block_reason,
    }
