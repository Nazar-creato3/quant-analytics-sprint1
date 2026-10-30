from fastapi import APIRouter, Depends, HTTPException, Query

from app.services.position_liquidity.service import portfolio_liquidity
from app.services.qa.feature_flags import is_enabled
from app.services.qa.session_user import require_session_user_id

router = APIRouter(tags=["liquidity"])


@router.get("/portfolio/{portfolio_id}/liquidity")
def get_liquidity(
    portfolio_id: str,
    participation: float = Query(0.1),
    user_id: str = Depends(require_session_user_id),
) -> dict:
    if not is_enabled("qa_position_liquidity"):
        raise HTTPException(status_code=404, detail="liquidity flag off")
    return portfolio_liquidity(user_id, portfolio_id, participation=participation)
