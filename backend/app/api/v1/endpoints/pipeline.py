from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.deps import get_current_user_email, get_db, get_user_db
from app.core.logging import get_logger
from app.db.models import Maneuver, ManeuverReport
from app.services.pipeline.maneuver_counts import count_tradeable_persisted
from app.schemas.schemas import (
    ManeuverReportOut,
    PaginatedResponse,
    PipelineRunRequest,
    PipelineRunResponse,
)
from app.services.settings.watchlist import get_effective_watchlist

router = APIRouter(prefix="/pipeline", tags=["pipeline"])
logger = get_logger(__name__)

_STALE_PIPELINE_SEC = 120.0
# A started run may take 6-10 min on the stand; the page waits 15 min and the
# worker drops runs older than 15 min. Reporting failure earlier hid finished reports.
_STALE_STARTED_SEC = 900.0


def _celery_result_payload(result: object) -> dict:
    if isinstance(result, dict):
        return result
    return {}


def _pipeline_failure_from_payload(payload: dict) -> str | None:
    inner = str(payload.get("status") or "").lower()
    if inner in {"halted", "failed"}:
        return str(payload.get("reason") or payload.get("error") or inner)
    return None


def _read_celery_task_snapshot(task_id: str) -> dict[str, Any]:
    """Sync Celery/Redis read — run in a thread from async handlers."""
    if task_id.startswith("inline-"):
        return {"state": "STARTED", "payload": None, "failure_raw": None}

    from celery.result import AsyncResult

    from app.tasks.celery_app import celery_app

    ar = AsyncResult(task_id, app=celery_app)
    state = ar.state
    payload: dict[str, Any] | None = None
    failure_raw: str | None = None
    if state == "SUCCESS" and ar.ready():
        try:
            raw = ar.result
            payload = raw if isinstance(raw, dict) else {"raw": raw}
        except Exception as exc:  # noqa: BLE001
            logger.warning("celery_result_decode_failed", task_id=task_id, error=str(exc)[:120])
    elif state == "FAILURE" and ar.ready():
        try:
            failure_raw = str(ar.result)
        except Exception as exc:  # noqa: BLE001
            failure_raw = str(exc)
    return {"state": state, "payload": payload, "failure_raw": failure_raw}


async def _celery_task_snapshot(task_id: str) -> dict[str, Any]:
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_read_celery_task_snapshot, task_id),
            timeout=8.0,
        )
    except asyncio.TimeoutError:
        logger.warning("celery_status_read_timeout", task_id=task_id)
        return {"state": "STARTED", "payload": None, "failure_raw": None, "timed_out": True}


def _run_age_seconds(meta: dict | None) -> float | None:
    if not meta:
        return None
    raw = meta.get("created_at") or meta.get("updated_at")
    if not raw:
        return None
    try:
        created = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - created).total_seconds())
    except ValueError:
        return None


@router.post("/run", response_model=PipelineRunResponse)
async def trigger_pipeline(
    body: PipelineRunRequest,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> PipelineRunResponse:
    """
    Trigger the full intelligence pipeline:
    market data → features → news → ML → risk → maneuvers.

    Returns immediately with a run_id. Poll /pipeline/status/{run_id} for results.
    """
    from app.services.portfolio.user_scope import get_user_by_email

    user = await get_user_by_email(db, email)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")

    watchlist = body.watchlist or await get_effective_watchlist(db, email)
    run_id = str(uuid.uuid4())

    from app.services.portfolio.metrics import (
        _user_confidence_threshold,
        _user_effective_deploy_cap,
        user_account_total_usd,
    )
    from app.services.risk.portfolio_sizing import resolve_deploy_cap_for_sizing
    from app.utils.pipeline_dispatch import dispatch_pipeline_task
    from app.utils.pipeline_tracker import track_run

    account_total = await user_account_total_usd(email, db)
    if body.portfolio_size is not None:
        portfolio_size = resolve_deploy_cap_for_sizing(float(body.portfolio_size), account_total)
    else:
        portfolio_size = await _user_effective_deploy_cap(email, db)
    confidence_threshold = await _user_confidence_threshold(email)

    try:
        logger.info(
            "Pipeline triggered",
            user=email,
            watchlist=watchlist,
            run_id=run_id,
            settings_cap=float(body.portfolio_size) if body.portfolio_size is not None else None,
            account_total=account_total,
            sizing_portfolio=portfolio_size,
            confidence_threshold=confidence_threshold,
        )

        task_id = dispatch_pipeline_task(
            run_id=run_id,
            watchlist=watchlist,
            portfolio_size=portfolio_size,
            confidence_threshold=confidence_threshold,
            triggered_by=email,
            skip_auto_execute=True,
            owner_user_id=user.id,
        )
        track_run(run_id, task_id, triggered_by=email)
        return PipelineRunResponse(
            run_id=run_id,
            task_id=task_id,
            status="queued",
            message="Анализ в очереди. Обновите статус через минуту.",
            eta_seconds=30,
        )
    except Exception as exc:
        logger.error("Failed to queue pipeline", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Не удалось поставить анализ в очередь. Попробуйте позже.",
        )


async def _report_id_for_pipeline_run(
    db: AsyncSession, run_id: str, user_id: str
) -> str | None:
    """DB fallback when in-memory/Redis tracker missed the run (user-scoped)."""
    result = await db.execute(
        select(ManeuverReport.id)
        .where(
            ManeuverReport.pipeline_run_id == run_id,
            ManeuverReport.created_by == user_id,
        )
        .limit(1)
    )
    row = result.scalar_one_or_none()
    return str(row) if row is not None else None


async def _pipeline_status_counts(
    db: AsyncSession, report_id: str | None, user_id: str
) -> tuple[int | None, int | None]:
    if not report_id:
        return None, None
    from app.services.portfolio.user_scope import report_for_user

    result = await db.execute(
        report_for_user(user_id, report_id).options(selectinload(ManeuverReport.maneuvers))
    )
    report = result.scalar_one_or_none()
    if not report:
        return None, None
    ctx = report.market_context if isinstance(report.market_context, dict) else {}
    slots_raw = ctx.get("maneuver_slots")
    slots = int(slots_raw) if slots_raw is not None else settings.MANEUVER_COUNT
    tradeable = count_tradeable_persisted(report.maneuvers)
    return tradeable, slots


def _pipeline_run_owned(meta: dict[str, Any] | None, *, email: str, user_id: str) -> bool:
    """True only when this session started the run. A missing owner fails closed."""
    if not meta:
        return False
    owner = str(meta.get("triggered_by") or "")
    if not owner:
        return False
    return owner in {email, f"ops:{email}", f"beat:{email}", f"beat:user:{user_id}"}


@router.get("/status/{run_id}", response_model=PipelineRunResponse)
async def get_pipeline_status(
    run_id: str,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> PipelineRunResponse:
    """Check the status of a pipeline run by its run_id."""
    from app.services.portfolio.user_scope import get_user_by_email

    user = await get_user_by_email(db, email)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")

    try:
        from app.utils.pipeline_tracker import get_run

        meta = get_run(run_id)
        if meta and not _pipeline_run_owned(meta, email=email, user_id=str(user.id)):
            meta = None
        task_id = meta.get("task_id") if meta else None

        if meta and meta.get("status") == "complete":
            report_id = meta.get("report_id")
            if not report_id:
                report_id = await _report_id_for_pipeline_run(db, run_id, user.id)
            tradeable, slots = await _pipeline_status_counts(db, report_id, user.id)
            return PipelineRunResponse(
                run_id=run_id,
                task_id=task_id,
                status="complete",
                message="Анализ завершён.",
                report_id=report_id,
                tradeable_count=tradeable,
                maneuver_slots=slots,
            )
        if meta and meta.get("status") == "failed":
            return PipelineRunResponse(
                run_id=run_id,
                task_id=task_id,
                status="failed",
                message=meta.get("error", "Pipeline failed"),
            )

        if not task_id:
            report_id = await _report_id_for_pipeline_run(db, run_id, user.id)
            if report_id:
                tradeable, slots = await _pipeline_status_counts(db, report_id, user.id)
                return PipelineRunResponse(
                    run_id=run_id,
                    status="complete",
                    message="Pipeline complete (recovered from database).",
                    report_id=report_id,
                    tradeable_count=tradeable,
                    maneuver_slots=slots,
                )
            return PipelineRunResponse(
                run_id=run_id,
                status="unknown",
                message="Run not found; still waiting or invalid run_id.",
            )

        snapshot = await _celery_task_snapshot(task_id)
        celery_state = str(snapshot.get("state") or "PENDING")
        age_sec = _run_age_seconds(meta)

        if celery_state in {"PENDING", "STARTED", "RETRY"} and age_sec is not None:
            if age_sec > _STALE_PIPELINE_SEC and celery_state == "PENDING":
                return PipelineRunResponse(
                    run_id=run_id,
                    task_id=task_id,
                    status="failed",
                    message=(
                        "Анализ долго не стартует. Попробуйте позже."
                    ),
                )
            if age_sec > _STALE_STARTED_SEC and celery_state in {"STARTED", "RETRY"}:
                return PipelineRunResponse(
                    run_id=run_id,
                    task_id=task_id,
                    status="failed",
                    message=(
                        "Анализ прервался. Повторите через минуту."
                    ),
                )

        if celery_state == "SUCCESS":
            payload = _celery_result_payload(snapshot.get("payload"))
            failure_msg = _pipeline_failure_from_payload(payload)
            if failure_msg:
                return PipelineRunResponse(
                    run_id=run_id,
                    task_id=task_id,
                    status="failed",
                    message=failure_msg,
                )
            report_id = payload.get("report_id")
            if not report_id:
                report_id = await _report_id_for_pipeline_run(db, run_id, user.id)
            tradeable, slots = await _pipeline_status_counts(db, report_id, user.id)
            return PipelineRunResponse(
                run_id=run_id,
                task_id=task_id,
                status="complete",
                message="Анализ завершён.",
                report_id=report_id,
                tradeable_count=tradeable,
                maneuver_slots=slots,
            )
        if celery_state == "FAILURE":
            raw = str(snapshot.get("failure_raw") or "Pipeline failed")
            if "SIGKILL" in raw or "signal 9" in raw.lower() or "exited prematurely" in raw.lower():
                msg = "Анализ прервался из‑за нехватки ресурсов. Повторите позже."
            else:
                msg = "Анализ не удался. Попробуйте позже."
            return PipelineRunResponse(
                run_id=run_id,
                task_id=task_id,
                status="failed",
                message=msg,
            )
        in_progress_msg = (
            "Анализ ещё идёт. Обновите статус чуть позже."
            if snapshot.get("timed_out")
            else "Анализ выполняется."
        )
        return PipelineRunResponse(
            run_id=run_id,
            task_id=task_id,
            status=celery_state.lower(),
            message=in_progress_msg,
        )
    except Exception as exc:
        logger.warning("pipeline_status_failed", run_id=run_id, error=str(exc)[:200])
        return PipelineRunResponse(run_id=run_id, status="unknown", message="Статус сейчас недоступен.")


@router.get("/reports", response_model=PaginatedResponse)
async def list_reports(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> PaginatedResponse:
    """List maneuver reports for the authenticated user, newest first."""
    from app.services.portfolio.user_scope import get_user_by_email, reports_for_user

    user = await get_user_by_email(db, email)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")

    offset = (page - 1) * page_size
    scoped = reports_for_user(user.id)

    count_result = await db.execute(select(func.count()).select_from(scoped.subquery()))
    total = count_result.scalar_one()

    result = await db.execute(
        scoped.options(selectinload(ManeuverReport.maneuvers))
        .order_by(desc(ManeuverReport.created_at))
        .offset(offset)
        .limit(page_size)
    )
    reports = result.scalars().all()

    return PaginatedResponse(
        items=[ManeuverReportOut.model_validate(r) for r in reports],
        total=total,
        page=page,
        page_size=page_size,
        pages=max(1, (total + page_size - 1) // page_size),
    )


@router.get("/reports/{report_id}", response_model=ManeuverReportOut)
async def get_report(
    report_id: str,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> ManeuverReportOut:
    """Get a full maneuver report including all 10 maneuvers (user-scoped)."""
    from sqlalchemy.orm import selectinload

    from app.services.portfolio.user_scope import get_user_by_email, report_for_user

    user = await get_user_by_email(db, email)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")

    result = await db.execute(
        report_for_user(user.id, report_id).options(selectinload(ManeuverReport.maneuvers))
    )
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Отчёт не найден")
    return ManeuverReportOut.model_validate(report)


@router.get("/reports/{report_id}/text")
async def get_report_text(
    report_id: str,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> dict:
    """Get the human-readable text version of a report (user-scoped)."""
    from sqlalchemy.orm import selectinload

    from app.services.portfolio.user_scope import get_user_by_email, report_for_user

    user = await get_user_by_email(db, email)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")

    result = await db.execute(
        report_for_user(user.id, report_id).options(selectinload(ManeuverReport.maneuvers))
    )
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Отчёт не найден")

    out = ManeuverReportOut.model_validate(report)
    return {"report_id": report_id, "text": out.to_full_text()}
