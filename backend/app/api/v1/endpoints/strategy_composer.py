"""Strategy Composer API endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user_email, get_db
from app.schemas.strategy_composer import (
    ComposerBacktestOut,
    ComposerBacktestRequest,
    ComposerConfigIn,
    ComposerConfigOut,
    ComposerSchemaOut,
    ComposerValidationResult,
    CompiledStrategyConfig,
)
from app.services.strategy.composer.service import ComposerValidationError, StrategyComposerService

router = APIRouter(prefix="/strategy-composer", tags=["strategy-composer"])


def _service(db: AsyncSession) -> StrategyComposerService:
    return StrategyComposerService(db)


@router.get("/schema", response_model=ComposerSchemaOut)
async def get_composer_schema(
    _: str = Depends(get_current_user_email),
) -> ComposerSchemaOut:
    """Return allowed fields, operators, and strategy outcomes for the builder."""
    return StrategyComposerService.schema()


@router.get("/default", response_model=ComposerConfigOut)
async def get_default_config(
    _: str = Depends(get_current_user_email),
) -> ComposerConfigOut:
    """Return the starter composer template."""
    return StrategyComposerService.default_config()


@router.get("", response_model=ComposerConfigOut)
async def load_composer_config(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> ComposerConfigOut:
    """Load saved composer config for the authenticated user's profile."""
    svc = _service(db)
    profile_id = await svc.resolve_profile_id(email)
    config = await svc.load(profile_id)
    if config is None:
        config = StrategyComposerService.default_config()
    return config


@router.put("", response_model=ComposerConfigOut)
async def save_composer_config(
    body: ComposerConfigIn,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> ComposerConfigOut:
    """Validate and persist composer config on the user's profile."""
    svc = _service(db)
    profile_id = await svc.resolve_profile_id(email)
    try:
        saved = await svc.save(profile_id, body)
    except ComposerValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    await db.commit()
    return saved


@router.post("/validate", response_model=ComposerValidationResult)
async def validate_config(
    body: ComposerConfigIn,
    _: str = Depends(get_current_user_email),
) -> ComposerValidationResult:
    """Validate composer config without saving."""
    return StrategyComposerService.validate_config(body)


@router.post("/compile", response_model=CompiledStrategyConfig)
async def compile_config(
    body: ComposerConfigIn,
    _: str = Depends(get_current_user_email),
) -> CompiledStrategyConfig:
    """Compile composer config into StrategyMesh parameters."""
    try:
        from app.services.pretrade.policy import evaluate

        evaluate(
            kind="strategy",
            actor="human",
            user_id=str(_),
            ticker=str(getattr(body, "symbol", None) or "COMPOSER"),
            qty=1.0,
            price=1.0,
        )
        compiled = StrategyComposerService.compile_config(body)
        try:
            from app.services.forecast_log.emit import emit_bot_or_composer

            ticker = getattr(body, "symbol", None) or "COMPOSER"
            emit_bot_or_composer(
                ticker=str(ticker),
                direction=0,
                probability="0.5",
                section="composer",
                model_id="strategy_composer",
            )
        except Exception:
            raise
        return compiled
    except ComposerValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/backtest", response_model=ComposerBacktestOut)
async def backtest_composer_config(
    body: ComposerBacktestRequest,
    _: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> ComposerBacktestOut:
    """Purged walk-forward backtest of the IF/THEN rule on historical bars."""
    from datetime import datetime, timedelta, timezone

    from app.services.portfolio.risk_analytics import load_dated_closes
    from app.services.strategy.composer.service import ComposerValidationError, StrategyComposerService
    from app.services.strategy.composer.walk_forward_backtest import run_composer_walk_forward

    validation = StrategyComposerService.validate_config(body.config)
    if not validation.valid:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="; ".join(validation.errors))

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=int(body.lookback_days * 1.6))
    closes = await load_dated_closes(db, body.symbol.strip().upper(), start=start, end=end)
    result = run_composer_walk_forward(
        body.config,
        symbol=body.symbol.strip().upper(),
        dated_closes=closes,
    )
    return ComposerBacktestOut.model_validate(result.to_dict())
