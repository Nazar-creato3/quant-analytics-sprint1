"""Futures risk and hedge API (prompt 58A)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.services.futures_risk.service import explain
from app.services.qa.feature_flags import is_enabled
from app.services.qa.session_user import require_session_user_id

router = APIRouter(prefix="/futures", tags=["futures-risk"])


class PositionIn(BaseModel):
    ticker: str
    qty: float
    price: float | None = None
    point_value: float | None = None
    initial_margin: float | None = None
    funding_30d: float | None = None
    days_to_expiry: int | None = None
    basis: float | None = None
    perpetual: bool = False


class HedgeIn(BaseModel):
    positions: list[PositionIn]
    liquid_nav: float | None = None
    min_margin: float | None = None
    initial_margin: float | None = None
    beta: float | None = None
    hedge_share: float = Field(default=0.0, ge=0.0, le=1.0)
    hedge_fut_price: float | None = None
    hedge_point_value: float | None = None
    portfolio_vol: float | None = None
    index_vol: float | None = None


@router.post("/risk")
def post_futures_risk(body: HedgeIn, user_id: str = Depends(require_session_user_id)) -> dict:
    if not is_enabled("qa_futures_risk", user_id=user_id):
        raise HTTPException(status_code=404, detail="futures flag off")
    return explain(
        positions=[p.model_dump() for p in body.positions],
        liquid_nav=body.liquid_nav,
        min_margin=body.min_margin,
        initial_margin=body.initial_margin,
        beta=body.beta,
        hedge_share=body.hedge_share,
        hedge_fut_price=body.hedge_fut_price,
        hedge_point_value=body.hedge_point_value,
        portfolio_vol=body.portfolio_vol,
        index_vol=body.index_vol,
    )


@router.get("/desk")
async def get_futures_desk(mode: str = "paper", user_id: str = Depends(require_session_user_id)) -> dict:
    """Key FORTS contracts, the user's futures, cash for margin and hedge inputs."""
    from app.services.futures_desk.service import desk
    from app.utils.json_safe import sanitize_for_json

    return sanitize_for_json(await desk(user_id, "live" if mode == "live" else "paper"))


@router.get("/contracts")
async def get_futures_contracts(q: str = "", user_id: str = Depends(require_session_user_id)) -> dict:
    """Search any FORTS futures by code or name (for the contract calculator)."""
    from app.services.futures_desk.service import board, search
    from app.utils.json_safe import sanitize_for_json

    return sanitize_for_json({"items": search(await board(), q)})
