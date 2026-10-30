"""
Maneuver management: listing, approval, rejection, execution status.
"""
from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user_email, get_user_db
from app.utils.json_safe import finite_float
from app.core.logging import get_logger
from app.db.models import Maneuver, ManeuverStatus, StrategyType, TradingMode, User
from app.schemas.schemas import (
    ManeuverApprovalRequest,
    ManeuverCancelOut,
    ManeuverCancelRequest,
    ManeuverEditRequest,
    ManeuverOut,
    PaginatedResponse,
    TickerBookOut,
)
from app.utils.audit import AuditAction, audit
from app.services.portfolio.cancel_maneuver import (
    ManeuverNotCancellable,
    ManeuverNotFound,
    cancel_maneuver,
)
from app.services.portfolio.flatten import LiveFlattenNotSupported

router = APIRouter(prefix="/maneuvers", tags=["maneuvers"])
logger = get_logger(__name__)


def _log_actor(email: str) -> str:
    return hashlib.sha256((email or "").encode("utf-8")).hexdigest()[:12]

_APPROVABLE_STATUSES = frozenset(
    {
        ManeuverStatus.PENDING,
        ManeuverStatus.CANCELLED,
        ManeuverStatus.REJECTED,
        "pending",
        "pending_approval",
        "awaiting_approval",
    }
)
_ALREADY_APPROVED_STATUSES = frozenset(
    {
        ManeuverStatus.APPROVED,
        ManeuverStatus.EXECUTING,
        ManeuverStatus.FILLED,
    }
)
_NO_LONGER_PENDING_STATUSES = frozenset(
    {
        ManeuverStatus.APPROVED,
        ManeuverStatus.EXECUTING,
        ManeuverStatus.FILLED,
        ManeuverStatus.REJECTED,
        ManeuverStatus.CANCELLED,
    }
)
_PENDING_LIST_STATUSES = frozenset(
    {
        "pending",
        "pending_approval",
        "awaiting_approval",
    }
)


def _normalize_status(status: ManeuverStatus | str) -> str:
    if hasattr(status, "value"):
        return str(status.value)
    return str(status)


def _is_pending_list_query(status_filter: str | None) -> bool:
    if not status_filter:
        return False
    statuses = {s.strip().lower() for s in status_filter.split(",") if s.strip()}
    return bool(statuses & _PENDING_LIST_STATUSES)


async def _pending_confidence_meta(
    db: AsyncSession,
    *,
    user_id: str,
    threshold: float,
    maneuvers: list[Maneuver],
    tradeable_count: int,
) -> dict[str, Any] | None:
    """Structured empty-state hint when pending proposals fail the confidence gate."""
    from app.db.models import ManeuverReport
    from app.services.portfolio.user_scope import reports_for_user
    from app.services.risk.confidence_filter import build_confidence_filter_result

    if tradeable_count > 0:
        return None

    max_conf = None
    for maneuver in maneuvers:
        if maneuver.strategy_type == StrategyType.NO_TRADE:
            continue
        if max_conf is None or maneuver.confidence > max_conf:
            max_conf = maneuver.confidence

    if max_conf is None:
        try:
            result = await db.execute(
                reports_for_user(user_id)
                .order_by(desc(ManeuverReport.created_at))
                .limit(1)
            )
            report = result.scalar_one_or_none()
            if report and isinstance(report.market_context, dict):
                ctx_filter = report.market_context.get("confidence_filter")
                if isinstance(ctx_filter, dict) and ctx_filter.get("message"):
                    return {"confidence_filter": ctx_filter}
                ctx_max = report.market_context.get("confidence_filter", {})
                if isinstance(ctx_max, dict):
                    raw_max = ctx_max.get("max_available_confidence")
                    if raw_max is not None:
                        max_conf = float(raw_max)
        except Exception as exc:
            logger.warning("Could not load latest report confidence meta", error=str(exc))

    filter_result = build_confidence_filter_result(
        threshold,
        max_available_confidence=max_conf,
        tradeable_count=tradeable_count,
    )
    if not filter_result.threshold_too_high:
        return None
    return {"confidence_filter": filter_result.to_dict()}


async def _dispatch_maneuver_execution(maneuver_id: str) -> None:
    """Execute paper fills in-request; fall back to Celery if needed.

    Positions UI lists FILLED only — awaiting Celery left APPROVED stuck forever
    when the worker lagged. Local paper simulation fills instantly.
    """
    from app.services.execution.adapter import execute_maneuver

    # Paper fills instantly; a live order is sent and settled inline too. A
    # Celery retry after an inline failure reuses the same broker idempotency key.
    try:
        await execute_maneuver(maneuver_id)
        logger.info("Maneuver executed inline", maneuver_id=maneuver_id)
        return
    except Exception as exc:
        logger.warning(
            "Inline execution failed, falling back to Celery",
            maneuver_id=maneuver_id,
            error=str(exc),
        )

    try:
        from app.tasks.execution import execute_maneuver_task

        execute_maneuver_task.delay(maneuver_id=maneuver_id)
        logger.info("Maneuver execution dispatched", maneuver_id=maneuver_id)
    except Exception as exc:
        logger.warning(
            "Celery dispatch failed, scheduling background inline execution",
            maneuver_id=maneuver_id,
            error=str(exc),
        )

        async def _inline() -> None:
            try:
                await execute_maneuver(maneuver_id)
            except Exception as inline_exc:
                logger.error(
                    "Inline execution failed",
                    maneuver_id=maneuver_id,
                    error=str(inline_exc),
                )

        asyncio.create_task(_inline())


async def _reload_maneuver(db: AsyncSession, maneuver: Maneuver) -> Maneuver:
    """Reload maneuver from DB; recover the session if a prior commit failed."""
    try:
        await db.refresh(maneuver)
        return maneuver
    except Exception as exc:
        logger.warning("Maneuver refresh failed, reloading row", maneuver_id=maneuver.id, error=str(exc))
        try:
            await db.rollback()
        except Exception as rollback_exc:
            logger.warning("Rollback after refresh failure failed", error=str(rollback_exc))
        result = await db.execute(select(Maneuver).where(Maneuver.id == maneuver.id))
        reloaded = result.scalar_one_or_none()
        if reloaded is None:
            raise
        return reloaded


async def _maneuver_response(db: AsyncSession, maneuver: Maneuver) -> ManeuverOut:
    """Build API response; enrichment failures must never break approve."""
    try:
        maneuver = await _reload_maneuver(db, maneuver)
        item = ManeuverOut.model_validate(maneuver)
        await _enrich_maneuver_presentation(item, maneuver)
        try:
            await _attach_position_analytics(db, [maneuver], [item])
        except Exception as exc:
            logger.warning(
                "Position analytics skipped for maneuver response",
                maneuver_id=maneuver.id,
                error=str(exc),
            )
        return item
    except Exception as exc:
        logger.warning(
            "Maneuver response build failed — returning minimal row",
            maneuver_id=maneuver.id,
            error=str(exc),
        )
        try:
            await db.rollback()
        except Exception as rollback_exc:
            logger.warning("Rollback after response failure failed", error=str(rollback_exc))
        result = await db.execute(select(Maneuver).where(Maneuver.id == maneuver.id))
        reloaded = result.scalar_one_or_none()
        if reloaded is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maneuver not found")
        return ManeuverOut.model_validate(reloaded)


@router.get("", response_model=PaginatedResponse)
async def list_maneuvers(
    ticker: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    skip_confidence_filter: bool = Query(
        False,
        description="Return pending below user confidence threshold (cockpit edit).",
    ),
    include_orphans: bool = Query(
        False,
        description="Staff only: include pipeline orphan maneuvers (created_by IS NULL).",
    ),
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> PaginatedResponse:
    """List maneuvers with optional filtering by ticker and status."""
    from app.core.rbac_deps import get_user_and_role
    from app.domain.rbac import is_staff_admin_role
    from app.services.portfolio.user_scope import get_user_by_email, maneuvers_for_user

    user = await get_user_by_email(db, email)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    _user, role = await get_user_and_role(db, email)
    staff = is_staff_admin_role(role)
    from app.services.portfolio.expiration_close import close_expired_for_user
    from app.services.portfolio.barrier_close import close_barrier_hits

    await close_expired_for_user(db, user.id)
    await close_barrier_hits(db, user_id=user.id)

    query = maneuvers_for_user(
        user.id,
        staff_include_orphans=bool(staff and include_orphans),
    ).order_by(desc(Maneuver.created_at))
    if ticker:
        query = query.where(Maneuver.ticker == ticker.upper())
    if status_filter:
        if "," in status_filter:
            statuses = [s.strip() for s in status_filter.split(",") if s.strip()]
            query = query.where(Maneuver.status.in_(statuses))
        else:
            query = query.where(Maneuver.status == status_filter)

    count_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = count_result.scalar_one()

    offset = (page - 1) * page_size
    pending_query = _is_pending_list_query(status_filter)
    fetch_limit = 200 if pending_query else page_size
    fetch_offset = 0 if pending_query else offset
    result = await db.execute(query.offset(fetch_offset).limit(fetch_limit))
    maneuvers = result.scalars().all()

    meta: dict[str, Any] | None = None
    if pending_query and not skip_confidence_filter:
        from app.services.portfolio.metrics import _user_confidence_threshold
        from app.services.risk.confidence_filter import passes_confidence_threshold

        threshold = await _user_confidence_threshold(email)
        tradeable_pending = [
            m for m in maneuvers if m.strategy_type != StrategyType.NO_TRADE
        ]
        above_threshold = [
            m
            for m in tradeable_pending
            if passes_confidence_threshold(m.confidence, threshold)
        ]
        # Show backfill / below-threshold proposals saved by the pipeline (catalyst marks them).
        below_marked = [
            m
            for m in tradeable_pending
            if m not in above_threshold
            and m.catalyst
            and "ниже порога" in m.catalyst
        ]
        proposable = above_threshold + [m for m in below_marked if m not in above_threshold]
        if not proposable and tradeable_pending:
            best = max(tradeable_pending, key=lambda m: float(m.confidence or 0))
            proposable = [best]
        meta = {
            "confidence_filter": {
                "threshold": threshold,
                "tradeable_count": len(proposable),
                "above_threshold_count": len(above_threshold),
                "backfill_count": len(proposable) - len(above_threshold),
            }
        }
        if not proposable:
            extra = await _pending_confidence_meta(
                db,
                user_id=user.id,
                threshold=threshold,
                maneuvers=maneuvers,
                tradeable_count=0,
            )
            if extra:
                meta.update(extra)
        total = len(proposable)
        maneuvers = proposable[offset : offset + page_size]
    elif pending_query and skip_confidence_filter:
        # Cockpit Edit Position: show pending even below threshold so edits stay available.
        tradeable = [m for m in maneuvers if m.strategy_type != StrategyType.NO_TRADE]
        total = len(tradeable)
        maneuvers = tradeable[offset : offset + page_size]

    items = [ManeuverOut.model_validate(m) for m in maneuvers]
    from app.services.portfolio.metrics import _user_effective_deploy_cap
    from app.services.risk.portfolio_sizing import deploy_bounds

    list_cap = await _user_effective_deploy_cap(email, db)
    per_name, _max_book, _min_ticket = deploy_bounds(list_cap)
    for item in items:
        if str(getattr(item.strategy_type, "value", item.strategy_type)).lower() == "no_trade":
            continue
        if str(getattr(item.status, "value", item.status)).lower() != "pending":
            continue
        usd = float(item.position_size_usd or 0.0)
        if list_cap <= 0:
            continue
        item.position_size_usd = round(min(usd, per_name, list_cap), 2)
    for item, maneuver in zip(items, maneuvers, strict=False):
        await _enrich_maneuver_presentation(item, maneuver)
    enrich_started = datetime.now(timezone.utc)
    await _attach_position_analytics(db, list(maneuvers), items)
    enrich_done = datetime.now(timezone.utc)

    # Attach live snapshot metadata for open-position queries (positions tab).
    open_statuses = {"approved", "filled", "executing"}
    status_tokens = {s.strip().lower() for s in (status_filter or "").split(",") if s.strip()}
    is_open_positions_query = bool(status_tokens & open_statuses)
    if is_open_positions_query:
        missing_price = any(i.current_price is None for i in items)
        live_meta = {
            "server_now": enrich_done.isoformat(),
            "last_refresh_at": enrich_started.isoformat(),
            "data_freshness_seconds": max(0, int((enrich_done - enrich_started).total_seconds())),
            "stale": missing_price,
        }
        meta = {**(meta or {}), "live_snapshot": live_meta}
        logger.info(
            "live_positions_list",
            email=email,
            count=len(items),
            stale=missing_price,
            as_of=enrich_done.isoformat(),
        )

    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=max(1, (total + page_size - 1) // page_size),
        meta=meta,
    )


async def _enrich_maneuver_presentation(item: ManeuverOut, maneuver: Maneuver) -> None:
    """Flatten signal_meta onto ManeuverOut response fields."""
    meta = getattr(maneuver, "signal_meta", None) or {}
    if not isinstance(meta, dict):
        return
    item.signal_meta = meta
    item.regime_context = meta.get("regime_context")
    item.key_drivers = meta.get("key_drivers")
    item.risk_flags = meta.get("risk_flags")
    item.suggested_position_pct = meta.get("suggested_position_pct")


def _audit_decision_details(maneuver: Maneuver, *, action: str, note: str | None, risk_note: str | None) -> dict:
    """Audit payload for approve/reject (spec A.2b)."""
    meta = getattr(maneuver, "signal_meta", None) or {}
    regime = meta.get("regime_label") if isinstance(meta, dict) else None
    if not regime and maneuver.report_id:
        regime = None
    return {
        "action": action,
        "note": note,
        "risk_note": risk_note,
        "ticker": maneuver.ticker,
        "score": round(float(maneuver.confidence), 4),
        "factors": meta.get("key_drivers") if isinstance(meta, dict) else None,
        "regime": regime or (meta.get("regime_label") if isinstance(meta, dict) else None),
        "rank": maneuver.rank,
        "direction": str(maneuver.direction),
        "position_size_usd": maneuver.position_size_usd,
    }


async def _attach_position_analytics(
    db: AsyncSession,
    maneuvers: list[Maneuver],
    items: list[ManeuverOut],
) -> None:
    """Enrich outgoing maneuvers with current price, approx net profit, time-to-close."""
    try:
        from app.services.portfolio.position_analytics import enrich_maneuvers

        enrichment = await enrich_maneuvers(db, maneuvers)
        for item, maneuver in zip(items, maneuvers, strict=False):
            data = enrichment.get(item.id)
            if not data:
                continue
            item.current_price = finite_float(data.get("current_price"))
            item.approx_profit = finite_float(data.get("approx_profit"))
            item.unrealized_pnl = finite_float(data.get("unrealized_pnl"))
            item.time_to_close = data.get("time_to_close")
            if data.get("horizon_end_at"):
                item.horizon_end_at = str(data["horizon_end_at"])
                item.expiry_at = item.horizon_end_at
            if item.stop_loss is None:
                item.stop_loss = finite_float(data.get("display_stop_loss"))
            if item.take_profit is None:
                item.take_profit = finite_float(data.get("display_take_profit"))
            tp_prob = finite_float(data.get("tp_hit_probability"))
            if tp_prob is not None:
                item.tp_hit_probability = tp_prob
            if data.get("profit_disclosure"):
                item.profit_disclosure = str(data["profit_disclosure"])
            if data.get("horizon_expired") is not None:
                item.horizon_expired = bool(data["horizon_expired"])
            pnl_low = finite_float(data.get("expected_pnl_low"))
            if pnl_low is not None:
                item.expected_pnl_low = pnl_low
            pnl_high = finite_float(data.get("expected_pnl_high"))
            if pnl_high is not None:
                item.expected_pnl_high = pnl_high
            ret_low = finite_float(data.get("expected_return_low"))
            if ret_low is not None:
                item.expected_return_low = ret_low
            ret_high = finite_float(data.get("expected_return_high"))
            if ret_high is not None:
                item.expected_return_high = ret_high
    except Exception as exc:  # analytics are best-effort — never break the list
        logger.warning("Position analytics enrichment failed", error=str(exc))


def _apply_expiry_overrides(
    maneuver: Maneuver,
    *,
    time_horizon: str | None = None,
    expiry_at: datetime | None = None,
) -> dict[str, str]:
    """Persist user-controlled duration without a schema migration."""
    from app.services.portfolio.position_analytics import apply_horizon_expiry_overrides

    return apply_horizon_expiry_overrides(
        maneuver,
        time_horizon=time_horizon,
        expiry_at=expiry_at,
    )


@router.get("/book/{ticker}", response_model=TickerBookOut)
async def get_ticker_book(
    ticker: str,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> TickerBookOut:
    """Average Buy + strategy zone + Buy/Sell markers for the desk chart."""
    from app.core.rbac_deps import get_user_and_role
    from app.domain.rbac import is_staff_admin_role
    from app.services.portfolio.barrier_close import close_barrier_hits
    from app.services.portfolio.cost_basis import ticker_book
    from app.services.portfolio.expiration_close import close_expired_for_user
    from app.services.portfolio.user_scope import get_user_by_email

    user = await get_user_by_email(db, email)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    _user, role = await get_user_and_role(db, email)
    staff = is_staff_admin_role(role)
    await close_expired_for_user(db, user.id)
    await close_barrier_hits(db, user_id=user.id)
    payload = await ticker_book(
        db,
        user.id,
        ticker,
        staff_include_orphans=bool(staff),
    )
    return TickerBookOut.model_validate(payload)


@router.get("/{maneuver_id}", response_model=ManeuverOut)
async def get_maneuver(
    maneuver_id: str,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> ManeuverOut:
    """Get a single maneuver by ID."""
    from app.services.portfolio.user_scope import get_user_by_email, load_maneuver_for_user

    user = await get_user_by_email(db, email)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    maneuver = await load_maneuver_for_user(
        db,
        user.id,
        maneuver_id,
        staff_include_orphans=False,
    )
    if not maneuver:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maneuver not found")
    item = ManeuverOut.model_validate(maneuver)
    await _enrich_maneuver_presentation(item, maneuver)
    await _attach_position_analytics(db, [maneuver], [item])
    return item


@router.post("/{maneuver_id}/approve", response_model=ManeuverOut)
async def approve_maneuver(
    maneuver_id: str,
    body: ManeuverApprovalRequest,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> ManeuverOut:
    """
    Approve or reject a pending maneuver.
    Paper mode: approve triggers an instant simulated fill so audit/P&L work.
    Live mode: records the decision only — orders go through Direct Deals.
    """
    from app.services.portfolio.user_scope import get_user_by_email, load_maneuver_for_user

    user = await get_user_by_email(db, email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    maneuver = await load_maneuver_for_user(
        db,
        user.id,
        maneuver_id,
        staff_include_orphans=False,
    )
    if not maneuver:
        raise HTTPException(status_code=404, detail="Maneuver not found")

    norm_status = _normalize_status(maneuver.status)
    approved_values = {s.value if hasattr(s, "value") else str(s) for s in _ALREADY_APPROVED_STATUSES}
    no_longer_pending_values = {
        s.value if hasattr(s, "value") else str(s) for s in _NO_LONGER_PENDING_STATUSES
    }

    if body.action == "approve" and norm_status in approved_values:
        return await _maneuver_response(db, maneuver)

    if body.action == "reject" and norm_status in no_longer_pending_values:
        return await _maneuver_response(db, maneuver)

    if norm_status not in _APPROVABLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Маневр уже в статусе «{norm_status}», изменение невозможно.",
        )

    if maneuver.status in (ManeuverStatus.CANCELLED, ManeuverStatus.REJECTED):
        maneuver.status = ManeuverStatus.PENDING

    user_result = await db.execute(select(User).where(User.email == email))
    user = user_result.scalar_one_or_none()

    risk_note: str | None = None
    if body.action == "approve":
        live_requested = (body.trading_mode or "paper") == "live"
        if live_requested and user is not None:
            from app.services.trading_keys.user_executor import live_unavailable_reason

            reason = await live_unavailable_reason(db, user.id)
            if reason:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=reason)
        maneuver.trading_mode = TradingMode.LIVE if live_requested else TradingMode.PAPER
        expiry_changes = _apply_expiry_overrides(
            maneuver,
            time_horizon=body.time_horizon,
            expiry_at=body.expiry_at,
        )
        # ── Position-sizing guardrails (bankruptcy protection) ──────────────
        # Re-check against live portfolio exposure and cap / reject BEFORE any
        # order is placed. Scales the size down in place when it fits partially.
        from app.services.risk.position_limits import (
            apply_decision_to_maneuver,
            evaluate_position_limits,
        )

        decision = await evaluate_position_limits(db, maneuver, email)
        if not decision.allowed:
            logger.warning(
                "Maneuver rejected by risk limits",
                maneuver_id=maneuver_id,
                reason=decision.reason,
            )
            await audit.log(
                db,
                action=AuditAction.MANEUVER_REJECT,
                user_id=user.id if user else None,
                resource_type="maneuver",
                resource_id=maneuver_id,
                details={"reason": decision.reason, "source": "risk_limits"},
                success=False,
            )
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=decision.reason)

        if decision.scaled:
            apply_decision_to_maneuver(maneuver, decision)
            risk_note = decision.reason
            logger.info(
                "Maneuver size scaled by risk limits",
                maneuver_id=maneuver_id,
                original=decision.original_size_usd,
                approved=decision.approved_size_usd,
            )

        maneuver.status = ManeuverStatus.APPROVED
        maneuver.approved_at = datetime.now(timezone.utc)
        maneuver.approved_by = user.id if user else None
        await db.commit()
        await _reload_maneuver(db, maneuver)
        # Approve = execution in the mode chosen at approval: a virtual fill on
        # paper, a real broker order on live (the executor applies its own
        # hard limits). The maneuver's trading_mode decides, not a global flag.
        try:
            await _dispatch_maneuver_execution(maneuver_id)
            await _reload_maneuver(db, maneuver)
            logger.info(
                "Maneuver approved and dispatched",
                maneuver_id=maneuver_id,
                user=_log_actor(email),
                mode=str(getattr(maneuver.trading_mode, "value", maneuver.trading_mode)),
                status=str(maneuver.status),
                fill_price=getattr(maneuver, "fill_price", None),
            )
        except Exception as exc:
            logger.warning(
                "Paper fill after approve failed — left APPROVED",
                maneuver_id=maneuver_id,
                error=str(exc),
            )
            logger.info(
                "Maneuver approved (decision only — no auto-execution)",
                maneuver_id=maneuver_id,
                user=_log_actor(email),
                status=str(maneuver.status),
            )

    elif body.action == "reject":
        maneuver.status = ManeuverStatus.REJECTED
        await db.commit()
        logger.info("Maneuver rejected", maneuver_id=maneuver_id, user=_log_actor(email))

    # Build the HTTP response before audit logging — audit.log commits on the
    # request session and can expire/invalidate the maneuver row while execution
    # is racing to FILLED; response must never depend on post-audit session state.
    out = await _maneuver_response(db, maneuver)

    audit_action = AuditAction.MANEUVER_APPROVE if body.action == "approve" else AuditAction.MANEUVER_REJECT
    try:
        await audit.log(
            db,
            action=audit_action,
            user_id=user.id if user else None,
            resource_type="maneuver",
            resource_id=maneuver_id,
            details=_audit_decision_details(
                maneuver,
                action=body.action,
                note=body.note,
                risk_note=risk_note,
            )
            | ({"expiry": expiry_changes} if "expiry_changes" in locals() and expiry_changes else {}),
        )
    except Exception as exc:
        logger.warning(
            "Audit log failed after maneuver action — response already built",
            maneuver_id=maneuver_id,
            action=body.action,
            error=str(exc),
        )

    if body.action == "approve":
        try:
            from app.utils.ws_notify import notify_pipeline_sync

            notify_pipeline_sync(
                "maneuver_approved",
                {"maneuver_id": maneuver_id, "ticker": maneuver.ticker, "owner_email": email},
            )
        except Exception as exc:
            logger.warning(
                "Pipeline notify failed after approve",
                maneuver_id=maneuver_id,
                error=str(exc),
            )

    return out


@router.patch("/{maneuver_id}", response_model=ManeuverOut)
async def edit_maneuver(
    maneuver_id: str,
    body: ManeuverEditRequest,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> ManeuverOut:
    """Edit a pending maneuver or open (filled/executing) paper position."""
    from app.services.portfolio.user_scope import get_user_by_email, load_maneuver_for_user

    user = await get_user_by_email(db, email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    maneuver = await load_maneuver_for_user(
        db,
        user.id,
        maneuver_id,
        staff_include_orphans=False,
    )
    if not maneuver:
        raise HTTPException(status_code=404, detail="Манёвр не найден")

    editable = {
        ManeuverStatus.PENDING,
        ManeuverStatus.APPROVED,
        ManeuverStatus.EXECUTING,
        ManeuverStatus.FILLED,
    }
    if maneuver.status not in editable:
        # GA16-326: do not expose status enum to the client.
        raise HTTPException(
            status_code=409,
            detail="Сейчас этот манёвр нельзя изменить.",
        )

    is_open = maneuver.status in {
        ManeuverStatus.FILLED,
        ManeuverStatus.EXECUTING,
        ManeuverStatus.APPROVED,
    }

    changes: dict = {}
    if body.size_usd is not None:
        maneuver.position_size_usd = body.size_usd
        changes["position_size_usd"] = body.size_usd
    if body.entry_price is not None:
        if is_open and maneuver.fill_price:
            # Keep fill price as truth for open positions — ignore entry edits.
            pass
        else:
            maneuver.entry_zone_low = body.entry_price
            maneuver.entry_zone_high = body.entry_price
            changes["entry_price"] = body.entry_price
    if body.stop_loss is not None:
        maneuver.stop_loss = body.stop_loss
        changes["stop_loss"] = body.stop_loss
    if body.take_profit is not None:
        maneuver.take_profit = body.take_profit
        changes["take_profit"] = body.take_profit
    if body.time_horizon is not None and body.time_horizon.strip():
        maneuver.time_horizon = body.time_horizon.strip()
        changes["time_horizon"] = maneuver.time_horizon
    changes.update(
        _apply_expiry_overrides(
            maneuver,
            time_horizon=body.time_horizon,
            expiry_at=body.expiry_at,
        )
    )
    if not changes:
        raise HTTPException(status_code=400, detail="No editable fields provided.")

    user_result = await db.execute(select(User).where(User.email == email))
    user = user_result.scalar_one_or_none()
    await audit.log(
        db,
        action=AuditAction.MANEUVER_EDIT,
        user_id=user.id if user else None,
        resource_type="maneuver",
        resource_id=maneuver_id,
        details={"changes": changes, "note": body.note},
    )
    await db.commit()
    await db.refresh(maneuver)
    item = ManeuverOut.model_validate(maneuver)
    await _attach_position_analytics(db, [maneuver], [item])
    return item


@router.post("/{maneuver_id}/cancel", response_model=ManeuverCancelOut)
async def cancel_maneuver_endpoint(
    maneuver_id: str,
    body: ManeuverCancelRequest | None = None,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> ManeuverCancelOut:
    """Cancel one maneuver or close one open paper position without affecting others."""
    payload = body or ManeuverCancelRequest()
    try:
        from app.services.portfolio.user_scope import get_user_by_email

        user = await get_user_by_email(db, email)
        result = await cancel_maneuver(
            db,
            maneuver_id,
            email,
            reason=payload.reason or "operator cancel",
            note=payload.note,
            staff_include_orphans=False,
        )
    except ManeuverNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maneuver not found")
    except ManeuverNotCancellable as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
    except LiveFlattenNotSupported as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    return ManeuverCancelOut(
        maneuver_id=result.maneuver_id,
        ticker=result.ticker,
        status_before=result.status_before,
        status_after=result.status_after,
        action=result.action,
        size_usd=result.size_usd,
        realized_pnl=result.realized_pnl,
        message=result.message,
    )
