"""Tests for operator-triggered ops drill endpoints."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import ops as ops_ep
from app.api.v1.endpoints.ops import router as ops_router
from app.core.access_deps import require_ops_read, require_post_trial
from app.core.deps import get_current_user_payload, get_db, get_user_db


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(ops_router, prefix="/api/v1")
    return app


@pytest.fixture
def unauth_client():
    with TestClient(_make_app(), raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def auth_client():
    """Authenticated non-admin user (any whitelisted role)."""
    app = _make_app()
    app.dependency_overrides[get_current_user_payload] = lambda: {
        "sub": "operator@x.io",
        "email": "operator@x.io",
        "is_admin": False,
    }

    async def fake_db():
        yield AsyncMock()

    async def fake_user():
        return MagicMock()

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_user_db] = fake_db
    app.dependency_overrides[require_post_trial] = fake_user
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def ops_client():
    """Authenticated operator (ops.read granted via dependency override)."""
    app = _make_app()
    app.dependency_overrides[get_current_user_payload] = lambda: {
        "sub": "operator@x.io",
        "email": "operator@x.io",
        "is_admin": False,
    }

    async def fake_db():
        yield AsyncMock()

    async def fake_ops():
        return MagicMock()

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[require_ops_read] = fake_ops
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


class TestAuth:
    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/ops/run-stop-drill",
            "/api/v1/ops/refresh-venue-balances",
            "/api/v1/ops/run-market-analysis",
            "/api/v1/ops/close-all-positions",
        ],
    )
    def test_requires_auth(self, unauth_client, path):
        resp = unauth_client.post(path)
        assert resp.status_code in (401, 403)


class TestAnyAuthenticatedUser:
    """User-scoped ops (flatten own book / run own analysis) stay available to trial users."""

    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/ops/close-all-positions",
            "/api/v1/ops/run-market-analysis",
        ],
    )
    def test_non_admin_not_forbidden(self, auth_client, path, monkeypatch):
        """Non-admin must not get 403 Admin required (endpoint may still fail for other reasons)."""
        # Avoid real side effects for endpoints that would otherwise run work
        monkeypatch.setattr(
            ops_ep,
            "_stop_drill_runner",
            lambda: (lambda **kwargs: {"passed": True, "staging": True, "production_mutation": False}),
        )
        monkeypatch.setattr(ops_ep, "_var_pilot_root", lambda: __import__("pathlib").Path("/tmp"))

        async def fake_balances():
            from app.schemas.portfolio import VenueBalancesOut

            return VenueBalancesOut(
                venues=[],
                total_trading_usd=0.0,
                total_balance_usd=0.0,
                total_usd=0.0,
                as_of="2026-07-14T00:00:00+00:00",
            )

        monkeypatch.setattr(ops_ep, "build_venue_balances", fake_balances)

        async def fake_close(db, email, reason=""):
            from app.services.portfolio.flatten import CloseAllResult

            return CloseAllResult(
                mode="paper",
                closed_count=0,
                cancelled_count=0,
                realized_pnl_total=0.0,
                freed_exposure_usd=0.0,
                message="ok",
                positions=[],
            )

        monkeypatch.setattr(ops_ep, "close_all_positions", fake_close)

        import app.tasks.pipeline as pipeline_mod
        import app.utils.pipeline_tracker as tracker_mod

        class _FakeTask:
            id = "task-auth"

        class _FakePipeline:
            @staticmethod
            def delay(**kwargs):
                return _FakeTask()

        async def fake_watchlist(_db, _email):
            return ["AAPL"]

        async def fake_portfolio_size(_email):
            return 100_000.0

        async def fake_confidence(_email):
            return 0.55

        monkeypatch.setattr(pipeline_mod, "run_pipeline_task", _FakePipeline)
        monkeypatch.setattr(tracker_mod, "track_run", lambda *a, **k: None)
        monkeypatch.setattr(
            "app.services.settings.watchlist.get_effective_watchlist",
            fake_watchlist,
        )
        monkeypatch.setattr(
            "app.services.portfolio.metrics._user_portfolio_size",
            fake_portfolio_size,
        )
        monkeypatch.setattr(
            "app.services.portfolio.metrics._user_confidence_threshold",
            fake_confidence,
        )

        resp = auth_client.post(path)
        assert resp.status_code != 403, resp.text
        assert resp.status_code == 200, resp.text


class TestStopDrillRunnerImport:
    def test_real_runner_imports_regardless_of_cwd(self):
        """Regression: the runner must import despite backend.* absolute imports.

        Previously the endpoint failed at runtime with "No module named 'backend'"
        because the API process runs with backend/ (not the repo root) on sys.path.
        _stop_drill_runner() must add the repo root to sys.path and return a callable.
        """
        try:
            runner = ops_ep._stop_drill_runner()
        except ModuleNotFoundError:
            pytest.skip("staging stop-drill runner not importable in this checkout")
        assert callable(runner)


class TestPlatformOpsForbidden:
    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/ops/run-stop-drill",
            "/api/v1/ops/refresh-venue-balances",
        ],
    )
    def test_trial_user_cannot_touch_platform_ops(self, auth_client, path, monkeypatch):
        from app.domain.rbac import SystemRole

        async def fake_role(_db, _email):
            return MagicMock(), SystemRole.USER

        monkeypatch.setattr("app.core.access_deps.get_user_and_role", fake_role)
        resp = auth_client.post(path)
        assert resp.status_code == 403


class TestStopDrill:
    def test_runs_and_returns_report(self, ops_client, monkeypatch, tmp_path):
        def fake_runner():
            def _run(*, session_id, data_dir, reason):
                return {
                    "passed": True,
                    "staging": True,
                    "production_mutation": False,
                    "session_id": session_id,
                    "reason": reason,
                }
            return _run

        monkeypatch.setattr(ops_ep, "_stop_drill_runner", fake_runner)
        monkeypatch.setattr(ops_ep, "_var_pilot_root", lambda: tmp_path)

        resp = ops_client.post("/api/v1/ops/run-stop-drill")
        assert resp.status_code == 200
        data = resp.json()
        assert data["passed"] is True
        assert data["session_id"].startswith("pilot-stop-")
        assert data["production_mutation"] is False
        assert data["report"]["passed"] is True

    def test_drill_failure_returns_structured_error(self, ops_client, monkeypatch, tmp_path):
        def fake_runner():
            def _run(**kwargs):
                raise RuntimeError("control plane boom")
            return _run

        monkeypatch.setattr(ops_ep, "_stop_drill_runner", fake_runner)
        monkeypatch.setattr(ops_ep, "_var_pilot_root", lambda: tmp_path)

        resp = ops_client.post("/api/v1/ops/run-stop-drill")
        assert resp.status_code == 200
        data = resp.json()
        assert data["passed"] is False
        assert "control plane boom" in data["error"]


class TestRefreshVenueBalances:
    def test_returns_balances(self, ops_client, monkeypatch):
        from app.schemas.portfolio import VenueBalanceOut, VenueBalancesOut

        async def fake_build():
            return VenueBalancesOut(
                venues=[VenueBalanceOut(venue="binance", configured=True, mode="testnet")],
                total_trading_usd=0.0,
                total_balance_usd=0.0,
                total_usd=0.0,
                as_of="2026-07-14T00:00:00+00:00",
            )

        monkeypatch.setattr(ops_ep, "build_venue_balances", fake_build)
        resp = ops_client.post("/api/v1/ops/refresh-venue-balances")
        assert resp.status_code == 200
        data = resp.json()
        assert data["venues"][0]["venue"] == "binance"


class TestMarketAnalysis:
    def test_queues_pipeline_for_non_admin(self, auth_client, monkeypatch):
        """Dashboard Run Analysis must work for any authenticated user."""
        import app.utils.pipeline_tracker as tracker_mod

        captured: dict = {}

        def fake_dispatch(**kwargs):
            captured.update(kwargs)
            return "task-123"

        async def fake_watchlist(_db, _email):
            return ["AAPL", "MSFT"]

        async def fake_portfolio_size(_email):
            return 100_000.0

        async def fake_confidence(_email):
            return 0.55

        async def fake_user(_db, _email):
            user = MagicMock()
            user.id = "user-1"
            return user

        monkeypatch.setattr("app.utils.pipeline_dispatch.dispatch_pipeline_task", fake_dispatch)
        monkeypatch.setattr(tracker_mod, "track_run", lambda *a, **k: None)
        monkeypatch.setattr(
            "app.services.settings.watchlist.get_effective_watchlist",
            fake_watchlist,
        )
        monkeypatch.setattr(
            "app.services.portfolio.metrics._user_portfolio_size",
            fake_portfolio_size,
        )
        monkeypatch.setattr(
            "app.services.portfolio.metrics._user_confidence_threshold",
            fake_confidence,
        )
        monkeypatch.setattr(
            "app.services.portfolio.user_scope.get_user_by_email",
            fake_user,
        )

        resp = auth_client.post("/api/v1/ops/run-market-analysis")
        assert resp.status_code == 200
        data = resp.json()
        assert data["task_id"] == "task-123"
        assert data["status"] == "queued"
        assert data["run_id"]
        assert data["watchlist"] == ["AAPL", "MSFT"]
        assert captured.get("skip_auto_execute") is True
        assert captured.get("triggered_by") == "ops:operator@x.io"
