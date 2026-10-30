"""SEC-08: public /health must not leak exception strings."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints.market import health_router
from app.core.deps import get_db


def _make_app(db_raises: bool = False) -> FastAPI:
    app = FastAPI()
    app.include_router(health_router, prefix="/api/v1")

    async def fake_db():
        session = AsyncMock()
        if db_raises:
            session.execute = AsyncMock(side_effect=RuntimeError("secret db host leaked"))
        else:
            session.execute = AsyncMock(return_value=MagicMock())
        yield session

    app.dependency_overrides[get_db] = fake_db
    return app


class TestHealthNoLeak:
    def test_liveness_does_not_probe_dependencies(self):
        app = _make_app(db_raises=True)
        with patch("redis.asyncio.from_url") as mock_redis:
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.get("/api/v1/health/live")

        assert resp.status_code == 200
        body = resp.json()
        assert body == {"status": "ok"}
        assert "version" not in body
        assert "env" not in body
        mock_redis.assert_not_called()

    def test_db_error_returns_coarse_status(self):
        app = _make_app(db_raises=True)
        with patch("redis.asyncio.from_url") as mock_redis:
            client_mock = AsyncMock()
            client_mock.ping = AsyncMock()
            client_mock.aclose = AsyncMock()
            mock_redis.return_value = client_mock
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.get("/api/v1/health")

        assert resp.status_code == 503
        data = resp.json()
        assert data["db"] == "error"
        assert data["status"] == "error"
        assert "secret" not in data["db"].lower()
        assert "leaked" not in str(data).lower()
        for leaked in ("version", "env", "secrets_backend", "vault_ok", "vault_keys_present"):
            assert leaked not in data

    def test_public_health_hides_build_fingerprint(self):
        app = _make_app()
        with patch("redis.asyncio.from_url") as mock_redis:
            client_mock = AsyncMock()
            client_mock.ping = AsyncMock()
            client_mock.aclose = AsyncMock()
            mock_redis.return_value = client_mock
            with TestClient(app, raise_server_exceptions=False) as client:
                live = client.get("/api/v1/health/live")
                ready = client.get("/api/v1/health")

        assert live.status_code == 200
        assert live.json() == {"status": "ok"}
        body = ready.json()
        assert ready.status_code == 200
        assert "version" not in body
        assert "env" not in body
        assert "APP_" not in str(body)

    def test_redis_error_marks_overall_status_error(self):
        app = _make_app(db_raises=False)
        with patch("redis.asyncio.from_url", side_effect=RuntimeError("redis down")):
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.get("/api/v1/health")

        assert resp.status_code == 503
        data = resp.json()
        assert data["redis"] == "error"
        assert data["status"] == "error"
        assert "redis down" not in str(data).lower()
