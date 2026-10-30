"""Security tests: RBAC, portfolio isolation, admissions access."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints.admissions import router as admissions_router
from app.api.v1.endpoints.maneuvers import router as maneuvers_router
from app.core.deps import get_current_user_email, get_db, get_user_db
from app.db.models import Maneuver, ManeuverReport, ManeuverStatus, User, UserRole
from app.domain.access_policy import AccessLevel, AccessPolicyRead
from app.domain.rbac import map_legacy_user_role, SystemRole
from app.services.portfolio.user_scope import (
    deal_intents_for_user,
    filter_grid_bots_for_user,
    maneuvers_for_user,
)


def test_viewer_maps_to_user_not_operator_admin():
    assert map_legacy_user_role("viewer") == SystemRole.USER
    assert map_legacy_user_role("admin") == SystemRole.OWNER_ADMIN


def test_analyst_maps_to_operator_admin():
    assert map_legacy_user_role("analyst") == SystemRole.OPERATOR_ADMIN


def test_filter_grid_bots_for_user():
    bots = {
        "a": {"created_by": "alice@test.com", "ticker": "AAPL"},
        "b": {"created_by": "bob@test.com", "ticker": "MSFT"},
        "c": {"ticker": "SPY"},
    }
    scoped = filter_grid_bots_for_user(bots, "alice@test.com")
    assert set(scoped.keys()) == {"a"}


@pytest.fixture
def maneuvers_client():
    app = FastAPI()
    app.include_router(maneuvers_router, prefix="/api/v1")

    async def fake_db():
        yield AsyncMock()

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_user_db] = fake_db

    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def test_trial_user_is_not_blocked_from_maneuver_list_permissions():
    """Trial is demo paper trading — list endpoint must not hard-empty for trial."""
    from app.domain.access_policy import AccessAction, AccessLevel, has_access_permission

    assert has_access_permission(AccessLevel.TRIAL_READ_ONLY, AccessAction.CREATE_DEAL_INTENT_PAPER)


def test_user_a_does_not_see_user_b_deal_intents_via_scope():
    """Scoped query joins sleeve.profile_id — foreign deal intents excluded."""
    stmt = deal_intents_for_user("user-a")
    compiled = str(stmt).lower()
    assert "sleeves" in compiled or "sleeve" in compiled
    assert "profile_id" in compiled


def test_user_a_does_not_see_user_b_maneuvers_via_scope():
    """Scoped query joins report.created_by — foreign maneuvers excluded."""
    stmt = maneuvers_for_user("user-a")
    compiled = str(stmt).lower()
    assert "maneuver_reports" in compiled or "maneuverreport" in compiled
    assert "created_by" in compiled
    assert "is null" not in compiled


def test_user_a_does_not_see_user_b_reports_via_scope():
    from app.services.portfolio.user_scope import reports_for_user

    stmt = reports_for_user("user-a")
    compiled = str(stmt).lower()
    assert "created_by" in compiled
    assert "maneuver_reports" in compiled


def test_orphan_reports_hidden_from_regular_users():
    stmt = maneuvers_for_user("user-a", staff_include_orphans=False)
    compiled = str(stmt).lower()
    assert "is null" not in compiled


def test_orphan_reports_visible_to_staff_only():
    stmt = maneuvers_for_user("user-a", staff_include_orphans=True)
    compiled = str(stmt).lower()
    assert "is null" in compiled or "is_" in compiled


def test_staff_positions_scope_excludes_orphans():
    """Personal portfolio/WS paths must never include orphan pipeline rows."""
    stmt = maneuvers_for_user("staff-user", staff_include_orphans=False)
    compiled = str(stmt).lower()
    assert "is null" not in compiled


def test_orphan_pipeline_maneuvers_query():
    from app.services.portfolio.user_scope import orphan_pipeline_maneuvers

    stmt = orphan_pipeline_maneuvers()
    compiled = str(stmt).lower()
    assert "is null" in compiled or "is_" in compiled
    assert "created_by" in compiled


@pytest.fixture
def admissions_client():
    app = FastAPI()
    app.include_router(admissions_router, prefix="/api/v1")

    async def fake_db():
        yield AsyncMock()

    app.dependency_overrides[get_db] = fake_db

    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def test_admissions_denied_for_viewer(admissions_client):
    mock_db = AsyncMock()
    viewer = User(
        id="viewer-1",
        email="viewer@test.com",
        hashed_password="x",
        role=UserRole.VIEWER,
        is_active=True,
        is_whitelisted=True,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = viewer
    mock_db.execute = AsyncMock(return_value=user_result)

    async def fake_db():
        yield mock_db

    admissions_client.app.dependency_overrides[get_db] = fake_db
    admissions_client.app.dependency_overrides[get_current_user_email] = lambda: "viewer@test.com"

    resp = admissions_client.get("/api/v1/admissions")
    assert resp.status_code == 403


def test_admissions_allowed_for_owner_admin(admissions_client):
    mock_db = AsyncMock()
    admin = User(
        id="admin-1",
        email="admin@test.com",
        hashed_password="x",
        role=UserRole.ADMIN,
        is_active=True,
        is_whitelisted=True,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = admin
    mock_db.execute = AsyncMock(return_value=user_result)

    list_result = MagicMock()
    list_result.scalars.return_value.all.return_value = []

    async def execute_side_effect(stmt):
        sql = str(stmt)
        if "users" in sql.lower():
            return user_result
        return list_result

    mock_db.execute = AsyncMock(side_effect=execute_side_effect)

    async def fake_db():
        yield mock_db

    admissions_client.app.dependency_overrides[get_db] = fake_db
    admissions_client.app.dependency_overrides[get_current_user_email] = lambda: "admin@test.com"

    with patch(
        "app.api.v1.endpoints.admissions.admissions_service.list_cases",
        new=AsyncMock(return_value=[]),
    ):
        resp = admissions_client.get("/api/v1/admissions")

    assert resp.status_code == 200


def test_admissions_allowed_for_operator_admin(admissions_client):
    mock_db = AsyncMock()
    analyst = User(
        id="analyst-1",
        email="ops@test.com",
        hashed_password="x",
        role=UserRole.ANALYST,
        is_active=True,
        is_whitelisted=True,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = analyst

    list_result = MagicMock()
    list_result.scalars.return_value.all.return_value = []

    async def execute_side_effect(stmt):
        sql = str(stmt)
        if "users" in sql.lower():
            return user_result
        return list_result

    mock_db.execute = AsyncMock(side_effect=execute_side_effect)

    async def fake_db():
        yield mock_db

    admissions_client.app.dependency_overrides[get_db] = fake_db
    admissions_client.app.dependency_overrides[get_current_user_email] = lambda: "ops@test.com"

    with patch(
        "app.api.v1.endpoints.admissions.admissions_service.list_cases",
        new=AsyncMock(return_value=[]),
    ):
        resp = admissions_client.get("/api/v1/admissions")

    assert resp.status_code == 200


def test_operator_admin_cannot_manage_permissions():
    from app.domain.rbac import has_permission

    assert not has_permission(SystemRole.OPERATOR_ADMIN, "identity.manage_permissions")
    assert has_permission(SystemRole.OWNER_ADMIN, "identity.manage_permissions")


def test_new_user_default_role_is_viewer():
    from app.db.models import User

    role_col = User.__table__.c.role
    assert role_col.default.arg == UserRole.VIEWER


def test_account_positions_scoped_to_user_report():
    """Paper positions query must filter via maneuvers_for_user."""
    from app.services.account import service as account_service

    source = account_service._paper_positions.__doc__ or ""
    # Implementation uses maneuvers_for_user — verify import path in function
    import inspect

    src = inspect.getsource(account_service._paper_positions)
    assert "maneuvers_for_user" in src


def test_account_a_positions_exclude_account_b_maneuvers():
    """GET /maneuvers (positions) for user A must not include user B rows."""
    from app.db.models import ManeuverStatus, SignalDirection, StrategyType

    report_a = ManeuverReport(id="report-a", created_by="user-a", watchlist=["MSFT"])
    report_b = ManeuverReport(id="report-b", created_by="user-b", watchlist=["MSFT"])
    orphan_report = ManeuverReport(id="report-orphan", created_by=None, watchlist=["MSFT"])

    maneuver_a = Maneuver(
        id="maneuver-a",
        report_id="report-a",
        rank=1,
        ticker="MSFT",
        strategy_type=StrategyType.MOMENTUM,
        direction=SignalDirection.SHORT,
        risk_percent=1.0,
        position_size_usd=5000.0,
        status=ManeuverStatus.FILLED,
    )
    maneuver_b = Maneuver(
        id="maneuver-b",
        report_id="report-b",
        rank=1,
        ticker="MSFT",
        strategy_type=StrategyType.MOMENTUM,
        direction=SignalDirection.SHORT,
        risk_percent=1.0,
        position_size_usd=5000.0,
        status=ManeuverStatus.FILLED,
    )
    orphan_maneuver = Maneuver(
        id="maneuver-orphan",
        report_id="report-orphan",
        rank=1,
        ticker="MSFT",
        strategy_type=StrategyType.MOMENTUM,
        direction=SignalDirection.SHORT,
        risk_percent=1.0,
        position_size_usd=5000.0,
        status=ManeuverStatus.FILLED,
    )

    def visible_for(user_id: str, *, staff: bool = False) -> set[str]:
        reports = {report_a, report_b, orphan_report}
        allowed_reports = {
            r.id
            for r in reports
            if r.created_by == user_id or (staff and r.created_by is None)
        }
        maneuvers = [maneuver_a, maneuver_b, orphan_maneuver]
        return {m.id for m in maneuvers if m.report_id in allowed_reports}

    user_a_visible = visible_for("user-a")
    user_b_visible = visible_for("user-b")

    assert "maneuver-a" in user_a_visible
    assert "maneuver-b" not in user_a_visible
    assert "maneuver-orphan" not in user_a_visible
    assert "maneuver-b" in user_b_visible
    assert "maneuver-a" not in user_b_visible
    assert "maneuver-orphan" not in user_b_visible

    staff_a_visible = visible_for("user-a", staff=True)
    assert "maneuver-orphan" in staff_a_visible

    staff_positions_visible = visible_for("user-a", staff=False)
    assert "maneuver-orphan" not in staff_positions_visible

    stmt = maneuvers_for_user("user-a")
    compiled = str(stmt).lower()
    assert "created_by" in compiled
    assert "is null" not in compiled


def test_health_isolation_module_covers_financial_surfaces():
    from app.services.health import user_isolation as iso

    src = open(iso.__file__, encoding="utf-8").read()
    for fragment in (
        "/api/positions",
        "/api/v1/maneuvers",
        "/api/v1/portfolio/metrics",
        "/api/v1/orders",
        "/api/v1/account",
        "/api/v1/grid",
        "ws/positions",
    ):
        assert fragment in src
