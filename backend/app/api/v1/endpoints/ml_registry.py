"""MLflow / feature-store ops endpoints for forecast model registry."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from app.core.deps import get_current_user_email
from app.services.forecast.feature_store import feast_status
from app.services.forecast.mlflow_registry import (
    export_registry_markdown,
    list_registered_models,
)

router = APIRouter(prefix="/ml", tags=["ml-registry"])


@router.get("/forecast-registry")
async def forecast_registry(email: str = Depends(get_current_user_email)):
    rows = [r.to_dict() for r in list_registered_models()]
    live = next((r for r in rows if r.get("is_live")), None)
    return {
        "models": rows,
        "live": live,
        "count": len(rows),
        "requested_by": email,
    }


@router.get("/forecast-registry.md", response_class=PlainTextResponse)
async def forecast_registry_markdown(email: str = Depends(get_current_user_email)):
    _ = email
    return export_registry_markdown()


@router.get("/feature-store/status")
async def feature_store_status(email: str = Depends(get_current_user_email)):
    _ = email
    return feast_status()


@router.get("/alpha/cards")
async def alpha_research_cards(email: str = Depends(get_current_user_email)):
    from app.services.alpha.model_card import list_research_cards

    rows = list_research_cards()
    return {"cards": rows, "count": len(rows), "requested_by": email}


class PromoteBody(BaseModel):
    name: str
    feature_freeze_id: str
    feature_lineage: str = ""
    confirm: bool = False
    n_train: int = 0
    outer_accuracy: float = 0.0
    outer_n: float = 0.0
    label_recipe: str = "triple_barrier+meta_label"
    cv_method: str = "nested_combinatorial_purged_cv"
    horizons: list[int] = Field(default_factory=lambda: [1, 5, 21])


@router.post("/alpha/promote")
async def alpha_human_promote(body: PromoteBody, email: str = Depends(get_current_user_email)):
    from app.services.alpha.model_card import build_card
    from app.services.platform_desk.promotion import promote_with_signoff

    card = build_card(
        name=body.name,
        metrics={"accuracy": body.outer_accuracy, "outer_accuracy": body.outer_accuracy, "outer_n": body.outer_n},
        n_train=body.n_train,
        feature_lineage=body.feature_lineage,
        feature_freeze_id=body.feature_freeze_id,
        label_recipe=body.label_recipe,
        cv_method=body.cv_method,
        horizons=body.horizons,
        promoted=False,
    )
    try:
        return promote_with_signoff(card, confirm=body.confirm, reviewer=email, totp_ok=None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
