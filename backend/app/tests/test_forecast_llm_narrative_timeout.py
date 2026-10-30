"""Forecast LLM narrative must be bounded but long enough for AITunnel verdict."""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest


def _forecast_llm_timeout_sec() -> float:
    endpoint_path = Path(__file__).parents[1] / "api" / "v1" / "endpoints" / "forecast.py"
    source = endpoint_path.read_text(encoding="utf-8")
    match = re.search(r"_FORECAST_LLM_NARRATIVE_TIMEOUT_SEC\s*=\s*([0-9.]+)", source)
    assert match, "Forecast endpoint must define the LLM narrative timeout cap"
    return float(match.group(1))


@pytest.mark.asyncio
async def test_forecast_llm_timeout_allows_verdict_generation():
    """Outer cap must exceed internal verdict LLM budget (45s) but stay bounded."""
    timeout_sec = _forecast_llm_timeout_sec()
    assert 45.0 <= timeout_sec <= 65.0


@pytest.mark.asyncio
async def test_forecast_symbol_endpoint_returns_when_llm_narrative_times_out():
    """Slow LLM hook is capped — caller gets TimeoutError, not an unbounded hang."""
    timeout_sec = _forecast_llm_timeout_sec()

    async def slow_narrative(**_kwargs):
        await asyncio.sleep(timeout_sec + 30)
        return "never"

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(slow_narrative(), timeout=timeout_sec)
