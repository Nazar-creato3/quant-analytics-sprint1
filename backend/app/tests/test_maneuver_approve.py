"""Tests for maneuver approve idempotency and single-click success."""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.db.models import ManeuverStatus, StrategyType


@contextmanager
def _approve_scope(maneuver, *, paper: bool = False, dispatch: AsyncMock | None = None):
    user = MagicMock(id="user-1", email="op@test.com")
    with patch(
        "app.services.portfolio.user_scope.get_user_by_email",
        AsyncMock(return_value=user),
    ), patch(
        "app.services.portfolio.user_scope.load_maneuver_for_user",
        AsyncMock(return_value=maneuver),
    ), patch(
        "app.services.execution.adapter.use_local_paper_simulation",
        return_value=paper,
    ), patch(
        "app.api.v1.endpoints.maneuvers._dispatch_maneuver_execution",
        dispatch or AsyncMock(),
    ):
        yield user


@pytest.mark.asyncio
async def test_approve_resets_cancelled_to_pending_before_approval():
    from app.api.v1.endpoints.maneuvers import approve_maneuver
    from app.schemas.schemas import ManeuverApprovalRequest

    maneuver = MagicMock()
    maneuver.id = "m-1"
    maneuver.ticker = "AAPL"
    maneuver.status = ManeuverStatus.CANCELLED
    maneuver.strategy_type = StrategyType.MOMENTUM
    maneuver.position_size_usd = 1000.0
    maneuver.direction = "long"
    maneuver.fill_price = None

    db = AsyncMock()
    db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=MagicMock(id="user-1")))
    )
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.rollback = AsyncMock()

    decision = MagicMock(allowed=True, scaled=False, reason="", original_size_usd=1000, approved_size_usd=1000)
    approved_out = MagicMock()

    with _approve_scope(maneuver), patch(
        "app.services.risk.position_limits.evaluate_position_limits",
        AsyncMock(return_value=decision),
    ), patch("app.utils.audit.audit.log", AsyncMock()), patch(
        "app.utils.ws_notify.notify_pipeline_sync"
    ), patch(
        "app.api.v1.endpoints.maneuvers._maneuver_response",
        AsyncMock(return_value=approved_out),
    ), patch(
        "app.api.v1.endpoints.maneuvers._reload_maneuver",
        AsyncMock(return_value=maneuver),
    ):
        result = await approve_maneuver(
            "m-1",
            ManeuverApprovalRequest(maneuver_id="m-1", action="approve"),
            email="op@test.com",
            db=db,
        )

    assert maneuver.status == ManeuverStatus.APPROVED
    assert result is approved_out


@pytest.mark.asyncio
async def test_approve_paper_dispatches_fill():
    from app.api.v1.endpoints.maneuvers import approve_maneuver
    from app.schemas.schemas import ManeuverApprovalRequest

    maneuver = MagicMock()
    maneuver.id = "m-paper"
    maneuver.ticker = "BTC-USD"
    maneuver.status = ManeuverStatus.PENDING
    maneuver.strategy_type = StrategyType.MOMENTUM
    maneuver.position_size_usd = 100.0
    maneuver.direction = "short"
    maneuver.fill_price = None

    db = AsyncMock()
    db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=MagicMock(id="user-1")))
    )
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    dispatch = AsyncMock()
    decision = MagicMock(allowed=True, scaled=False, reason="", original_size_usd=100, approved_size_usd=100)
    approved_out = MagicMock()

    with _approve_scope(maneuver, paper=True, dispatch=dispatch), patch(
        "app.services.risk.position_limits.evaluate_position_limits",
        AsyncMock(return_value=decision),
    ), patch("app.utils.audit.audit.log", AsyncMock()), patch(
        "app.utils.ws_notify.notify_pipeline_sync"
    ), patch(
        "app.api.v1.endpoints.maneuvers._maneuver_response",
        AsyncMock(return_value=approved_out),
    ), patch(
        "app.api.v1.endpoints.maneuvers._reload_maneuver",
        AsyncMock(return_value=maneuver),
    ):
        result = await approve_maneuver(
            "m-paper",
            ManeuverApprovalRequest(maneuver_id="m-paper", action="approve"),
            email="op@test.com",
            db=db,
        )

    assert result is approved_out
    dispatch.assert_awaited_once_with("m-paper")


@pytest.mark.asyncio
async def test_reapprove_already_approved_returns_maneuver_without_409():
    from app.api.v1.endpoints.maneuvers import approve_maneuver
    from app.schemas.schemas import ManeuverApprovalRequest

    maneuver = MagicMock()
    maneuver.id = "m-2"
    maneuver.ticker = "SPY"
    maneuver.status = ManeuverStatus.APPROVED

    db = AsyncMock()
    approved_out = MagicMock()

    with _approve_scope(maneuver), patch(
        "app.api.v1.endpoints.maneuvers._maneuver_response",
        AsyncMock(return_value=approved_out),
    ):
        result = await approve_maneuver(
            "m-2",
            ManeuverApprovalRequest(maneuver_id="m-2", action="approve"),
            email="op@test.com",
            db=db,
        )

    assert result is approved_out


@pytest.mark.asyncio
async def test_approve_filled_maneuver_returns_200_without_redispatch():
    """Idempotent approve on FILLED must not 500 (E2E: fill ok but HTTP 500)."""
    from app.api.v1.endpoints.maneuvers import approve_maneuver
    from app.schemas.schemas import ManeuverApprovalRequest

    maneuver = MagicMock()
    maneuver.id = "m-filled"
    maneuver.ticker = "TSLA"
    maneuver.status = ManeuverStatus.FILLED

    db = AsyncMock()
    filled_out = MagicMock()

    with _approve_scope(maneuver), patch(
        "app.api.v1.endpoints.maneuvers._maneuver_response",
        AsyncMock(return_value=filled_out),
    ):
        result = await approve_maneuver(
            "m-filled",
            ManeuverApprovalRequest(maneuver_id="m-filled", action="approve"),
            email="op@test.com",
            db=db,
        )

    assert result is filled_out


@pytest.mark.asyncio
async def test_approve_builds_response_before_audit_commit():
    """Response must be built before audit.log commits on the request session."""
    from app.api.v1.endpoints.maneuvers import approve_maneuver
    from app.schemas.schemas import ManeuverApprovalRequest

    maneuver = MagicMock()
    maneuver.id = "m-6"
    maneuver.ticker = "TSLA"
    maneuver.status = ManeuverStatus.PENDING
    maneuver.strategy_type = StrategyType.MOMENTUM
    maneuver.position_size_usd = 80.0
    maneuver.direction = "short"
    maneuver.fill_price = None

    db = AsyncMock()
    db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=MagicMock(id="user-1")))
    )
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    decision = MagicMock(allowed=True, scaled=False, reason="", original_size_usd=80, approved_size_usd=80)
    approved_out = MagicMock()
    call_order: list[str] = []

    async def _response_first(*_args, **_kwargs):
        call_order.append("response")
        return approved_out

    async def _audit_second(*_args, **_kwargs):
        call_order.append("audit")

    with _approve_scope(maneuver), patch(
        "app.services.risk.position_limits.evaluate_position_limits",
        AsyncMock(return_value=decision),
    ), patch(
        "app.api.v1.endpoints.maneuvers._reload_maneuver",
        AsyncMock(return_value=maneuver),
    ), patch(
        "app.api.v1.endpoints.maneuvers._maneuver_response",
        side_effect=_response_first,
    ), patch("app.utils.audit.audit.log", side_effect=_audit_second), patch(
        "app.utils.ws_notify.notify_pipeline_sync"
    ):
        result = await approve_maneuver(
            "m-6",
            ManeuverApprovalRequest(maneuver_id="m-6", action="approve"),
            email="op@test.com",
            db=db,
        )

    assert result is approved_out
    assert call_order == ["response", "audit"]


@pytest.mark.asyncio
async def test_first_click_approve_survives_audit_commit_failure():
    """Approval must return 200 even when audit logging poisons the session."""
    from app.api.v1.endpoints.maneuvers import approve_maneuver
    from app.schemas.schemas import ManeuverApprovalRequest

    maneuver = MagicMock()
    maneuver.id = "m-3"
    maneuver.ticker = "MSFT"
    maneuver.status = ManeuverStatus.PENDING
    maneuver.strategy_type = StrategyType.MOMENTUM
    maneuver.position_size_usd = 500.0
    maneuver.direction = "long"
    maneuver.fill_price = None

    db = AsyncMock()
    db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=MagicMock(id="user-1")))
    )
    db.commit = AsyncMock()
    db.refresh = AsyncMock(side_effect=SQLAlchemyError("session needs rollback"))
    db.rollback = AsyncMock()

    decision = MagicMock(allowed=True, scaled=False, reason="", original_size_usd=500, approved_size_usd=500)
    approved_out = MagicMock()
    approved_out.id = "m-3"
    approved_out.status = ManeuverStatus.APPROVED

    with _approve_scope(maneuver), patch(
        "app.services.risk.position_limits.evaluate_position_limits",
        AsyncMock(return_value=decision),
    ), patch("app.utils.audit.audit.log", AsyncMock()), patch(
        "app.utils.ws_notify.notify_pipeline_sync"
    ), patch(
        "app.api.v1.endpoints.maneuvers._reload_maneuver",
        AsyncMock(return_value=maneuver),
    ), patch(
        "app.api.v1.endpoints.maneuvers._maneuver_response",
        AsyncMock(return_value=approved_out),
    ):
        result = await approve_maneuver(
            "m-3",
            ManeuverApprovalRequest(maneuver_id="m-3", action="approve"),
            email="op@test.com",
            db=db,
        )

    assert result is approved_out
    assert maneuver.status == ManeuverStatus.APPROVED
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_audit_log_rollback_after_failed_commit():
    from app.utils.audit import audit

    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock(side_effect=RuntimeError("audit insert failed"))
    db.rollback = AsyncMock()

    await audit.log(
        db,
        action="maneuver_approve",
        user_id="user-1",
        resource_type="maneuver",
        resource_id="m-4",
        details={"action": "approve"},
    )

    db.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_dispatch_falls_back_to_inline_task_when_celery_unavailable():
    from app.api.v1.endpoints import maneuvers as maneuvers_module

    with patch.object(maneuvers_module, "asyncio") as asyncio_mock:
        asyncio_mock.create_task = MagicMock()
        with (
            patch(
                "app.services.execution.adapter.use_local_paper_simulation",
                return_value=False,
            ),
            patch(
                "app.tasks.execution.execute_maneuver_task",
                MagicMock(delay=MagicMock(side_effect=ConnectionError("redis down"))),
            ),
        ):
            await maneuvers_module._dispatch_maneuver_execution("m-5")

    asyncio_mock.create_task.assert_called_once()


@pytest.mark.asyncio
async def test_reject_after_approve_returns_200_with_current_state():
    """Reject on already-approved/filled maneuver must not 409 — UI removes from pending list."""
    from app.api.v1.endpoints.maneuvers import approve_maneuver
    from app.schemas.schemas import ManeuverApprovalRequest

    maneuver = MagicMock()
    maneuver.id = "m-approved"
    maneuver.ticker = "NVDA"
    maneuver.status = ManeuverStatus.APPROVED

    db = AsyncMock()
    current_out = MagicMock()

    with _approve_scope(maneuver), patch(
        "app.api.v1.endpoints.maneuvers._maneuver_response",
        AsyncMock(return_value=current_out),
    ):
        result = await approve_maneuver(
            "m-approved",
            ManeuverApprovalRequest(maneuver_id="m-approved", action="reject"),
            email="op@test.com",
            db=db,
        )

    assert result is current_out


@pytest.mark.asyncio
async def test_reject_filled_maneuver_returns_200_idempotent():
    from app.api.v1.endpoints.maneuvers import approve_maneuver
    from app.schemas.schemas import ManeuverApprovalRequest

    maneuver = MagicMock()
    maneuver.id = "m-filled-reject"
    maneuver.ticker = "AMZN"
    maneuver.status = ManeuverStatus.FILLED

    db = AsyncMock()
    filled_out = MagicMock()

    with _approve_scope(maneuver), patch(
        "app.api.v1.endpoints.maneuvers._maneuver_response",
        AsyncMock(return_value=filled_out),
    ):
        result = await approve_maneuver(
            "m-filled-reject",
            ManeuverApprovalRequest(maneuver_id="m-filled-reject", action="reject"),
            email="op@test.com",
            db=db,
        )

    assert result is filled_out
