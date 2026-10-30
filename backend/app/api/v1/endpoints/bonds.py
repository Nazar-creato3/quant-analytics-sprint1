"""Bond portfolio tab and issue card (prompt 56)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.schemas.bonds import BondIssueOut, BondPortfolioOut, BondStressOut
from app.services.bonds.service import bond_card, portfolio_bond_stress, portfolio_bonds
from app.services.qa.feature_flags import is_enabled
from app.services.qa.session_user import require_session_user_id

router = APIRouter(tags=["bonds"])


def _guard() -> None:
    if not is_enabled("qa_bonds"):
        raise HTTPException(status_code=404, detail="bonds flag off")


@router.get("/portfolio/{portfolio_id}/bonds", response_model=BondPortfolioOut)
def get_portfolio_bonds(
    portfolio_id: str,
    user_id: str = Depends(require_session_user_id),
) -> dict:
    _guard()
    return portfolio_bonds(user_id, portfolio_id)


@router.get("/portfolio/{portfolio_id}/bonds/stress", response_model=BondStressOut)
def get_portfolio_bond_stress(
    portfolio_id: str,
    shift_bp: int = Query(100),
    user_id: str = Depends(require_session_user_id),
) -> dict:
    _guard()
    return portfolio_bond_stress(user_id, portfolio_id, shift_bp=shift_bp)


@router.get("/bonds/{figi}")
def get_bond_card(figi: str, user_id: str = Depends(require_session_user_id)) -> dict:
    _guard()
    payload = bond_card(figi)
    BondIssueOut.model_validate({k: payload.get(k) for k in BondIssueOut.model_fields} | {"figi": figi})
    return payload
