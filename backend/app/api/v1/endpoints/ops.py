"""Ops endpoints for pilot visibility and operator-triggered drills."""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access_deps import require_ops_read, require_post_trial
from app.core.config import settings
from app.core.deps import get_current_user_email, get_current_user_payload, get_db, get_user_db
from app.db.models import User
from app.core.ui_features import raise_if_ui_removed
from app.core.logging import get_logger
from app.schemas.ops import (
    CloseAllPositionsOut,
    ClosedPositionOut,
    LlmStatusOut,
    MarketAnalysisRunOut,
    PilotStatusOut,
    StopDrillRunOut,
)
from app.schemas.portfolio import VenueBalancesOut
from app.services.ops.pilot_status import _var_pilot_root, build_pilot_status, build_pilot_status_async
from app.services.portfolio.flatten import LiveFlattenNotSupported, close_all_positions
from app.services.portfolio.venue_balances import build_venue_balances

router = APIRouter(prefix="/ops", tags=["ops"])
logger = get_logger(__name__)

_VENUE_BALANCES_CACHE_KEY = "ops:venue_balances"


def _repo_root() -> Path:
    """Repo root = parent of ``backend/``, derived from this file's location.

    ``ops.py`` lives at ``<repo>/backend/app/api/v1/endpoints/ops.py`` so the
    repo root is ``parents[5]``. Kept cwd-independent on purpose.
    """
    return Path(__file__).resolve().parents[5]


def _stop_drill_runner():
    """Lazily import + return the staging stop-drill runner (in-process, no subprocess).

    The ``grid_bot`` package uses absolute ``backend.grid_bot.*`` imports, which
    only resolve when the repo root (the parent of ``backend/``) is importable.
    The API process runs with ``backend/`` on ``sys.path`` (so ``app`` is the
    top-level package), which means ``backend`` itself is NOT importable and the
    import fails with "No module named 'backend'". Ensure the repo root is on
    ``sys.path`` first so the drill runs regardless of the current working
    directory or which interpreter launched the server.
    """
    repo_root = str(_repo_root())
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    from backend.grid_bot.scripts.staging_stop_drill import run_staging_stop_drill

    return run_staging_stop_drill


@router.get("/connector-health")
async def get_connector_health(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
):
    """Per-connector health aggregation for internal ops (Gap Analysis #10)."""
    from app.core.rbac_deps import get_user_and_role
    from app.domain.rbac import has_permission
    from app.services.ops.connector_health import build_connector_health

    _user, role = await get_user_and_role(db, email)
    if not has_permission(role, "ops.read") and not has_permission(role, "*"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="ops.read required")
    return await build_connector_health(db)


@router.get("/llm-status", response_model=LlmStatusOut)
async def get_llm_status(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> LlmStatusOut:
    """Compact LLM / AITunnel status for global navbar indicator (not per-page banners)."""
    from app.core.config import get_settings
    from app.core.rbac_deps import get_user_and_role
    from app.domain.rbac import has_permission
    settings = get_settings()
    show_balance = False
    try:
        _user, role = await get_user_and_role(db, email)
        show_balance = has_permission(role, "ops.read") or has_permission(role, "*")
    except HTTPException:
        show_balance = False
    # GA16-350: never expose flag names, vendor names, or machine reason codes to the UI.
    if not settings.LLM_ENABLED:
        logger.info("llm_status unavailable: llm_disabled")
        return LlmStatusOut(
            available=False,
            message_ru="AI-анализ временно недоступен",
            reason=None,
        )
    if not (settings.AITUNNEL_API_KEY or "").strip():
        logger.info("llm_status unavailable: no_api_key")
        return LlmStatusOut(
            available=False,
            message_ru="AI-анализ временно недоступен",
            reason=None,
        )

    try:
        from app.services.llm.aitunnel_balance import assess_balance

        assessment = await assess_balance(settings)
        balance = assessment.get("balance_rub")
        balance_out = float(balance) if (show_balance and balance is not None) else None
        if assessment.get("skipped"):
            logger.info(
                "llm_status skipped reason=%s",
                str(assessment.get("reason") or "skipped"),
            )
            return LlmStatusOut(
                available=False,
                message_ru="AI-анализ временно недоступен",
                reason=None,
                balance_rub=balance_out,
            )
        if assessment.get("status") == "passed":
            return LlmStatusOut(
                available=True,
                message_ru="AI-анализ доступен",
                reason=None,
                balance_rub=balance_out,
            )
        detail = str(assessment.get("error") or assessment.get("detail") or "").strip()
        logger.info(
            "llm_status unavailable reason=%s detail=%s",
            str(assessment.get("reason") or "balance_low"),
            detail[:200],
        )
        return LlmStatusOut(
            available=False,
            message_ru="AI-анализ временно недоступен",
            reason=None,
            balance_rub=balance_out,
        )
    except Exception as exc:
        logger.warning("llm_status_probe_failed", error=str(exc)[:200])
        return LlmStatusOut(
            available=False,
            message_ru="AI-анализ временно недоступен",
            reason=None,
        )


@router.get("/twenty-crm/health")
async def twenty_crm_health(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
):
    """Live probe of Twenty CRM API (application origination sync)."""
    from app.core.rbac_deps import get_user_and_role
    from app.domain.rbac import has_permission
    from app.services.crm.twenty import twenty_crm_client
    from app.services.ops.connector_health import record_connector_failure, record_connector_success

    _user, role = await get_user_and_role(db, email)
    if not has_permission(role, "ops.read") and not has_permission(role, "*"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="ops.read required")

    payload = await twenty_crm_client.health_check()
    if payload.get("ok"):
        await record_connector_success("twenty_crm", detail="REST probe ok")
    else:
        await record_connector_failure("twenty_crm", detail=payload.get("error") or payload.get("detail"))
    return payload


@router.get("/pilot-status", response_model=PilotStatusOut)
async def get_pilot_status(
    _: User = Depends(require_ops_read),
    db: AsyncSession = Depends(get_db),
) -> PilotStatusOut:
    """Phase 4 pilot read-only status — limits, venue lock, audit paths, verify commands."""
    raise_if_ui_removed("pilot")
    return await build_pilot_status_async(db)


@router.post("/run-stop-drill", response_model=StopDrillRunOut)
async def run_stop_drill_endpoint(
    payload: dict = Depends(get_current_user_payload),
    _: User = Depends(require_ops_read),
) -> StopDrillRunOut:
    """Run the staging stop drill (no production mutation) and return its report.

    Operators only. Writes a drill audit JSONL under the pilot data dir.
    """
    session_id = f"pilot-stop-{uuid.uuid4().hex[:8]}"
    data_dir = _var_pilot_root() / "stop_drill"
    try:
        run_staging_stop_drill = _stop_drill_runner()

        report = run_staging_stop_drill(
            session_id=session_id,
            data_dir=Path(data_dir),
            reason="operator ops-api stop drill",
        )
        audit_file = str(Path(data_dir) / "stop_drill_audit.jsonl")
        logger.info("Ops stop drill complete", session_id=session_id, passed=report.get("passed"))
        return StopDrillRunOut(
            passed=bool(report.get("passed")),
            session_id=session_id,
            reason="operator ops-api stop drill",
            data_dir=str(data_dir),
            audit_file=audit_file,
            staging=bool(report.get("staging", True)),
            production_mutation=bool(report.get("production_mutation", False)),
            report=report,
        )
    except Exception as exc:  # noqa: BLE001 - surface as structured failure
        logger.error("Ops stop drill failed", error=str(exc))
        return StopDrillRunOut(
            passed=False,
            session_id=session_id,
            reason="operator ops-api stop drill",
            data_dir=str(data_dir),
            error=str(exc),
        )


@router.post("/refresh-venue-balances", response_model=VenueBalancesOut)
async def refresh_venue_balances_endpoint(
    _: User = Depends(require_ops_read),
) -> VenueBalancesOut:
    """Recompute platform venue balances (env keys). Operators only — never trial users."""
    balances = await build_venue_balances()
    try:
        from app.utils.cache import cache_set

        await cache_set(_VENUE_BALANCES_CACHE_KEY, balances.model_dump(), ttl=120)
    except Exception as exc:  # noqa: BLE001 - cache is best-effort
        logger.warning("Venue balances cache refresh failed", error=str(exc))
    return balances


@router.post("/close-all-positions", response_model=CloseAllPositionsOut)
async def close_all_positions_endpoint(
    payload: dict = Depends(get_current_user_payload),
    db: AsyncSession = Depends(get_user_db),
) -> CloseAllPositionsOut:
    """Flatten the paper book: close open positions + cancel approved orders.

    Any authenticated user may run this. Frees portfolio exposure so new maneuvers
    can be approved. Paper-mode only — returns 409 while live trading is unlocked
    (a real book must be closed via the broker/kill-switch, not silently marked closed).
    """
    email = payload.get("sub", "operator")
    try:
        result = await close_all_positions(db, email, reason="operator ops-api flatten")
    except LiveFlattenNotSupported as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    logger.info(
        "Ops close-all complete",
        closed=result.closed_count,
        cancelled=result.cancelled_count,
        freed=result.freed_exposure_usd,
    )
    return CloseAllPositionsOut(
        mode=result.mode,
        closed_count=result.closed_count,
        cancelled_count=result.cancelled_count,
        realized_pnl_total=result.realized_pnl_total,
        freed_exposure_usd=result.freed_exposure_usd,
        message=result.message,
        positions=[ClosedPositionOut(**vars(p)) for p in result.positions],
    )


@router.post("/run-market-analysis", response_model=MarketAnalysisRunOut)
async def run_market_analysis_endpoint(
    body: dict | None = Body(None),
    payload: dict = Depends(get_current_user_payload),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_post_trial),
) -> MarketAnalysisRunOut:
    """Trigger the full market-intelligence pipeline (post-trial users only)."""
    from app.services.portfolio.user_scope import get_user_by_email
    from app.services.settings.watchlist import get_effective_watchlist

    operator = payload.get("sub", "operator")
    email = payload.get("email") or operator
    user = await get_user_by_email(db, email)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    watchlist = await get_effective_watchlist(db, email)
    if str((body or {}).get("mode") or "") == "live":
        from app.services.pipeline.live_universe import live_venues, restrict_to_brokers

        restricted = restrict_to_brokers(watchlist, await live_venues(db, user.id))
        if not restricted:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="В избранном нет бумаг Мосбиржи, которыми можно торговать через подключённого брокера.",
            )
        watchlist = restricted
    run_id = str(uuid.uuid4())
    try:
        from app.services.portfolio.metrics import _user_confidence_threshold, _user_effective_deploy_cap
        from app.utils.pipeline_dispatch import dispatch_pipeline_task
        from app.utils.pipeline_tracker import track_run

        portfolio_size = await _user_effective_deploy_cap(email, db)
        confidence_threshold = await _user_confidence_threshold(email)

        task_id: str
        try:
            task_id = dispatch_pipeline_task(
                run_id=run_id,
                watchlist=watchlist,
                portfolio_size=portfolio_size,
                confidence_threshold=confidence_threshold,
                triggered_by=f"ops:{email}",
                skip_auto_execute=True,
                owner_user_id=user.id,
            )
        except Exception as celery_exc:  # noqa: BLE001 — broker down, run inline
            import threading

            from app.tasks.pipeline import run_pipeline_task

            logger.warning(
                "Celery unavailable — running pipeline in background thread",
                run_id=run_id,
                error=str(celery_exc),
            )
            task_id = f"inline-{run_id}"

            def _run_inline() -> None:
                try:
                    run_pipeline_task.apply(
                        args=[run_id, watchlist, portfolio_size],
                        kwargs={
                            "confidence_threshold": confidence_threshold,
                            "triggered_by": f"ops:{email}",
                            "skip_auto_execute": True,
                            "owner_user_id": user.id,
                        },
                    )
                except Exception as inline_exc:  # noqa: BLE001
                    logger.error(
                        "Inline pipeline failed",
                        run_id=run_id,
                        error=str(inline_exc),
                    )

            threading.Thread(
                target=_run_inline,
                name=f"pipeline-{run_id[:8]}",
                daemon=True,
            ).start()

        track_run(run_id, task_id, triggered_by=f"ops:{email}")
        logger.info("Ops market analysis queued", run_id=run_id, task_id=task_id, user=email)
        return MarketAnalysisRunOut(
            run_id=run_id,
            task_id=task_id,
            status="queued",
            message="Pipeline queued. Poll /pipeline/status/{run_id} for results.",
            watchlist=watchlist,
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("Ops market analysis dispatch failed", error=str(exc))
        detail = (
            "Market analysis dispatch failed"
            if settings.is_production
            else f"Не удалось запустить анализ рынка: {exc}"
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=detail,
        )


@router.get("/pipeline-orphans")
async def list_pipeline_orphans(
    page: int = 1,
    page_size: int = 50,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
):
    """Admin-only list of pipeline maneuvers with no report owner (legacy orphans).

    Pre-isolation reports (created_by IS NULL) remain here — not visible in user dashboards.
    """
    from sqlalchemy import desc, func, select

    from app.core.rbac_deps import get_user_and_role
    from app.db.models import Maneuver
    from app.domain.rbac import has_permission, is_staff_admin_role
    from app.schemas.schemas import ManeuverOut, PaginatedResponse
    from app.services.portfolio.user_scope import orphan_pipeline_maneuvers

    _user, role = await get_user_and_role(db, email)
    if not is_staff_admin_role(role) and not has_permission(role, "ops.read"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="ops.read required")

    base = orphan_pipeline_maneuvers().order_by(desc(Maneuver.created_at))
    count_result = await db.execute(select(func.count()).select_from(base.subquery()))
    total = count_result.scalar_one()

    offset = max(0, (page - 1) * page_size)
    result = await db.execute(base.offset(offset).limit(page_size))
    maneuvers = result.scalars().all()

    return PaginatedResponse(
        items=[ManeuverOut.model_validate(m) for m in maneuvers],
        total=total,
        page=page,
        page_size=page_size,
        pages=max(1, (total + page_size - 1) // page_size),
        meta={"label": "pipeline_orphans"},
    )
