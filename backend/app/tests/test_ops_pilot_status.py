"""Minimal tests for app ops endpoints."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI

from app.api.v1.endpoints.ops import router as ops_router
from app.core.access_deps import require_ops_read
from app.core.deps import get_current_user_payload, get_db
from app.services.ops import pilot_status
from app.services.ops.pilot_status import (
    KILL_SWITCH_AUDIT_NAME,
    KILL_SWITCH_DRILL_COMMAND,
    KILL_SWITCH_DRILL_REL,
    _parse_latest_kill_switch_drill,
    build_pilot_status,
)

REQUIRED_KEYS = {
    "phase4_bundle_command",
    "pilot_limits",
    "pilot_venue",
    "venue_connectivity",
    "app_trading_mode",
    "paper_trading_enabled",
    "paper_capabilities",
    "last_pipeline_run",
    "grid_bot_tick",
    "forecast_refresh",
    "audit_paths",
    "last_drill_files",
    "grid_bot_test_counts",
    "docs_links",
    "kill_switch_drill",
}


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(ops_router, prefix="/api/v1")

    async def fake_db():
        yield AsyncMock()

    app.dependency_overrides[get_db] = fake_db
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


class TestOpsPilotStatus:
    def test_build_pilot_status_has_schema_keys(self):
        payload = build_pilot_status()
        data = payload.model_dump()
        assert REQUIRED_KEYS.issubset(data.keys())
        assert data["grid_bot_test_counts"]["expected_count"] == 994

    def test_pilot_status_requires_auth(self, client):
        resp = client.get("/api/v1/ops/pilot-status")
        assert resp.status_code in (401, 403, 422)

    def test_pilot_status_returns_410_when_ui_removed(self, client):
        from unittest.mock import MagicMock

        from app.core.deps import get_current_user_payload

        app = client.app
        app.dependency_overrides[get_current_user_payload] = lambda: {
            "sub": "operator@x.io",
            "is_admin": False,
        }

        async def fake_ops():
            return MagicMock()

        app.dependency_overrides[require_ops_read] = fake_ops
        resp = client.get("/api/v1/ops/pilot-status")
        assert resp.status_code == 410
        assert "removed" in resp.json()["detail"].lower()

    def test_kill_switch_drill_command_from_repo_root(self):
        assert "Set-Location" not in KILL_SWITCH_DRILL_COMMAND
        assert "backend.grid_bot.scripts.staging_kill_switch_drill" in KILL_SWITCH_DRILL_COMMAND
        assert "backend/var/staging/kill_switch_drill" in KILL_SWITCH_DRILL_COMMAND

    def test_parse_latest_kill_switch_drill_reads_final_passed_status(self, tmp_path: Path):
        audit_path = tmp_path / KILL_SWITCH_AUDIT_NAME
        stale = {
            "event_type": "kill_switch_drill",
            "payload": {
                "kill_switch_drill": {
                    "passed": False,
                    "session_id": "old",
                    "drill_id": "old-drill",
                    "ts_utc": "2026-07-11T00:00:00+00:00",
                }
            },
        }
        latest = {
            "event_type": "kill_switch_drill",
            "payload": {
                "kill_switch_drill": {
                    "passed": True,
                    "session_id": "staging-kill-switch-drill-01",
                    "drill_id": "new-drill",
                    "ts_utc": "2026-07-12T00:00:00+00:00",
                }
            },
        }
        audit_path.write_text(
            "\n".join(json.dumps(row) for row in (stale, latest)) + "\n",
            encoding="utf-8",
        )

        report = _parse_latest_kill_switch_drill(audit_path)
        assert report is not None
        assert report["passed"] is True
        assert report["session_id"] == "staging-kill-switch-drill-01"

    def test_pilot_limits_reads_backend_dotenv(self, monkeypatch):
        monkeypatch.delenv("GRID_PILOT_ENABLED", raising=False)
        monkeypatch.delenv("GRID_PILOT_MAX_NOTIONAL_PER_ORDER", raising=False)
        monkeypatch.delenv("GRID_PILOT_MAX_DAILY_LOSS", raising=False)
        monkeypatch.delenv("GRID_PILOT_MAX_ORDERS_PER_SESSION", raising=False)
        monkeypatch.delenv("GRID_PILOT_VENUE_ENABLED", raising=False)
        monkeypatch.delenv("GRID_PILOT_ALLOWED_VENUE", raising=False)
        monkeypatch.delenv("GRID_PILOT_ALLOWED_SYMBOLS", raising=False)
        pilot_status._dotenv_file.cache_clear()

        limits = build_pilot_status().pilot_limits
        venue = build_pilot_status().pilot_venue

        assert limits.enabled is True
        assert limits.source == "env"
        assert limits.max_notional_per_order == 100.0
        assert limits.max_daily_loss == 200.0
        assert limits.max_orders_per_session == 3

        assert venue.enabled is True
        assert venue.source == "env"
        assert venue.allowed_venue == "binance"
        assert venue.allowed_symbols == ["BTCUSDT"]

    def test_kill_switch_drill_status_uses_backend_var_path(self, monkeypatch, tmp_path: Path):
        backend_dir = tmp_path / "backend"
        drill_dir = backend_dir / KILL_SWITCH_DRILL_REL
        drill_dir.mkdir(parents=True)
        audit_path = drill_dir / KILL_SWITCH_AUDIT_NAME
        audit_path.write_text(
            json.dumps(
                {
                    "event_type": "kill_switch_drill",
                    "payload": {
                        "kill_switch_drill": {
                            "passed": True,
                            "session_id": "staging-kill-switch-drill-01",
                            "drill_id": "drill-1",
                            "ts_utc": "2026-07-12T00:00:00+00:00",
                        }
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(pilot_status, "_backend_dir", lambda: backend_dir)

        ks = build_pilot_status().kill_switch_drill
        assert ks.exists is True
        assert ks.passed is True
        assert ks.data_dir == str(drill_dir)
        assert ks.audit_file == str(audit_path)
