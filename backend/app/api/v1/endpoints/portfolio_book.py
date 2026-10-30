"""Read portfolio book (Prompt 05). Mode is required; paper/live never mixed."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.services.portfolio_book.service import assert_mode, positions_for, value_positions
from app.services.portfolio_book.store import BookModeError
from app.services.qa.feature_flags import is_enabled
from app.services.qa.session_user import require_session_user_id

router = APIRouter(prefix="/book", tags=["portfolio-book"])


@router.get("/positions")
def book_positions(
    user_id: str = Depends(require_session_user_id),
    mode: str = Query(..., pattern="^(paper|live)$"),
) -> dict:
    if not is_enabled("qa_portfolio_book"):
        raise HTTPException(status_code=404, detail="portfolio_book flag off")
    try:
        m = assert_mode(mode)
    except BookModeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    rows = positions_for(user_id=user_id, mode=m)
    return {"mode": m, "user_id": user_id, "positions": value_positions(rows, {}), "count": len(rows)}
