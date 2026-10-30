"""Tests for portfolio risk status endpoint and service."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints.portfolio import router as portfolio_router
from app.core.deps import get_current_user_email, get_db
from app.schemas.portfolio import PortfolioMetricsOut, RiskStatusOut
from app.services.portfolio.risk_status import build_risk_status


def _metrics(**overrides) -> PortfolioMetricsOut:
    base = dict(
        trading_usd=55_000.0,
        balance_usd=45_000.0,
        total_usd=100_000.0,
        currency="USD",
        mode="paper",
        source="internal",
        open_maneuvers=3,
        active_grid_bots=0,
        as_of="2026-07-19T12:00:00+00:00",
        exposure_pct=55.0,
        max_exposure_pct=80.0,
        cash_buffer_usd=20_000.0,
        max_position_usd=10_000.0,
        max_position_pct=10.0,
    )
    base.update(overrides)
    return PortfolioMetricsOut(**base)


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(portfolio_router, prefix="/api/v1")

    async def fake_db():
        yield AsyncMock()

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user_email] = lambda: "trader@test.com"

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


class TestRiskStatusService:
    @pytest.mark.asyncio
    async def test_caution_includes_explanation_and_factors(self):
        db = AsyncMock()
        with patch(
            "app.services.portfolio.risk_status.build_portfolio_metrics",
            new=AsyncMock(return_value=_metrics(exposure_pct=55.0)),
        ), patch(
            "app.services.portfolio.risk_status._user_daily_max_loss_pct",
            new=AsyncMock(return_value=5.0),
        ):
            result = await build_risk_status("trader@test.com", db)

        assert result.level == "caution"
        assert result.label == "Внимание"
        assert "Требует внимания" in result.explanation
        assert len(result.contributing_factors) >= 2
        assert any("Экспозиция портфеля" in f for f in result.contributing_factors)

    @pytest.mark.asyncio
    async def test_ok_when_low_exposure(self):
        db = AsyncMock()
        with patch(
            "app.services.portfolio.risk_status.build_portfolio_metrics",
            new=AsyncMock(return_value=_metrics(
                trading_usd=10_000.0,
                balance_usd=90_000.0,
                exposure_pct=10.0,
                open_maneuvers=1,
            )),
        ), patch(
            "app.services.portfolio.risk_status._user_daily_max_loss_pct",
            new=AsyncMock(return_value=5.0),
        ):
            result = await build_risk_status("trader@test.com", db)

        assert result.level == "ok"
        assert result.label == "В норме"
        assert "в норме" in result.explanation.lower()

    @pytest.mark.asyncio
    async def test_block_at_max_exposure(self):
        db = AsyncMock()
        with patch(
            "app.services.portfolio.risk_status.build_portfolio_metrics",
            new=AsyncMock(return_value=_metrics(
                trading_usd=80_000.0,
                balance_usd=20_000.0,
                exposure_pct=80.0,
            )),
        ), patch(
            "app.services.portfolio.risk_status._user_daily_max_loss_pct",
            new=AsyncMock(return_value=5.0),
        ):
            result = await build_risk_status("trader@test.com", db)

        assert result.level == "block"
        assert result.label == "Лимит"


class TestRiskStatusEndpoint:
    def test_risk_status_endpoint_requires_auth(self, client):
        app = client.app
        app.dependency_overrides.pop(get_current_user_email, None)
        resp = client.get("/api/v1/portfolio/risk-status")
        assert resp.status_code in (401, 403, 422)

    def test_risk_status_returns_payload(self, client):
        sample = RiskStatusOut(
            level="caution",
            label="Внимание",
            explanation="Требует внимания: экспозиция 55.0% выше 50%.",
            contributing_factors=["Экспозиция портфеля: 55.0% (лимит 80%)."],
            exposure_pct=55.0,
            max_exposure_pct=80.0,
            daily_max_loss_pct=5.0,
            open_maneuvers=3,
            trading_usd=55_000.0,
            cash_buffer_usd=20_000.0,
            as_of="2026-07-19T12:00:00+00:00",
        )
        with patch(
            "app.api.v1.endpoints.portfolio.build_risk_status",
            new=AsyncMock(return_value=sample),
        ):
            resp = client.get("/api/v1/portfolio/risk-status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["level"] == "caution"
        assert data["label"] == "Внимание"
        assert data["explanation"]
        assert len(data["contributing_factors"]) >= 1
