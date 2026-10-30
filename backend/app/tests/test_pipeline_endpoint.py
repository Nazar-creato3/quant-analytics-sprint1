"""Smoke tests for market analysis pipeline API."""
from __future__ import annotations

from app.core.config import settings


def test_pipeline_run_route_is_registered() -> None:
    from app.api.v1.endpoints.pipeline import router as pipeline_router

    paths = {getattr(route, "path", "") for route in pipeline_router.routes}
    assert "/pipeline/run" in paths


def test_pipeline_report_returns_ten_maneuvers() -> None:
    from app.services.risk.maneuver_generator import ManeuverGenerator

    gen = ManeuverGenerator()
    outs = gen.generate(market_data={})
    assert len(outs) == settings.MANEUVER_COUNT
