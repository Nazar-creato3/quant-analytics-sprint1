"""Tests for AITUNNEL balance monitoring."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services.llm.aitunnel_balance import BalanceSnapshot, assess_balance, fetch_balance_snapshot


@pytest.mark.asyncio
async def test_fetch_balance_snapshot_parses_api():
    mock_resp = AsyncMock()
    mock_resp.raise_for_status = lambda: None
    mock_resp.json = lambda: {"balance": 1234.5, "budget": 500.0}

    with patch("app.services.llm.aitunnel_balance.httpx.AsyncClient") as client_cls:
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.__aexit__.return_value = None
        client.get = AsyncMock(return_value=mock_resp)
        client_cls.return_value = client

        with patch("app.services.llm.aitunnel_balance._cache_last_balance", new=AsyncMock()):
            snap = await fetch_balance_snapshot()

    assert snap.balance_rub == 1234.5
    assert snap.budget_rub == 500.0
    assert snap.effective_rub == 500.0
    assert snap.source == "api"


@pytest.mark.asyncio
async def test_assess_balance_fails_when_below_24h_runway():
    snap = BalanceSnapshot(balance_rub=50.0, budget_rub=None, source="api")

    with patch("app.services.llm.aitunnel_balance.fetch_balance_snapshot", new=AsyncMock(return_value=snap)):
        with patch("app.services.llm.aitunnel_balance.spend_rub_last_hours", new=AsyncMock(return_value=60.0)):
            with patch("app.services.llm.aitunnel_balance.get_settings") as gs:
                settings = gs.return_value
                settings.LLM_ENABLED = True
                settings.AITUNNEL_API_KEY = "sk-test"
                settings.OPENAI_API_KEY = ""
                settings.AITUNNEL_BALANCE_ALERT_HOURS = 24
                settings.AITUNNEL_BALANCE_ALERT_RUB = 100
                verdict = await assess_balance(settings)

    assert verdict["status"] == "failed"
    assert verdict["effective_rub"] == 50.0
    assert verdict["threshold_rub"] == 60.0  # 60₽/24h spend → 24h runway threshold


@pytest.mark.asyncio
async def test_assess_balance_passes_when_sufficient():
    snap = BalanceSnapshot(balance_rub=5000.0, budget_rub=None, source="api")

    with patch("app.services.llm.aitunnel_balance.fetch_balance_snapshot", new=AsyncMock(return_value=snap)):
        with patch("app.services.llm.aitunnel_balance.spend_rub_last_hours", new=AsyncMock(return_value=5.0)):
            with patch("app.services.llm.aitunnel_balance.get_settings") as gs:
                settings = gs.return_value
                settings.LLM_ENABLED = True
                settings.AITUNNEL_API_KEY = "sk-test"
                settings.OPENAI_API_KEY = ""
                settings.AITUNNEL_BALANCE_ALERT_HOURS = 24
                settings.AITUNNEL_BALANCE_ALERT_RUB = 100
                verdict = await assess_balance(settings)

    assert verdict["status"] == "passed"
    assert verdict["hours_remaining"] == pytest.approx(5000.0 / (5.0 / 24.0))


@pytest.mark.asyncio
async def test_health_check_wired_and_skips_when_llm_disabled():
    from app.services.health.reporter import check_aitunnel_token_balance, run_health_report

    with patch(
        "app.services.llm.aitunnel_balance.assess_balance",
        new=AsyncMock(return_value={"skipped": True, "reason": "llm_disabled"}),
    ):
        row = await check_aitunnel_token_balance()
        assert row["name"] == "aitunnel_token_balance"
        assert row["status"] == "passed"
        assert row.get("skipped") == "llm_disabled"

    with patch("app.services.health.reporter.check_aitunnel_token_balance", new=AsyncMock(return_value={"name": "aitunnel_token_balance", "status": "passed"})):
        with patch("app.services.health.reporter.check_market_data_freshness", new=AsyncMock(return_value={"name": "market_data_freshness", "status": "passed"})):
            with patch("app.services.health.reporter.check_auth_login", new=AsyncMock(return_value={"name": "auth_login", "status": "passed"})):
                with patch("app.services.health.reporter.check_cross_user_position_isolation", new=AsyncMock(return_value={"name": "cross_user_position_isolation", "status": "passed"})):
                    with patch("app.services.health.reporter.check_chat_no_raw_debug", new=AsyncMock(return_value={"name": "chat_no_raw_debug", "status": "passed"})):
                        with patch("app.services.health.reporter.check_forecast_availability", new=AsyncMock(return_value={"name": "forecast_availability", "status": "passed"})):
                            with patch("app.services.health.reporter.check_forecast_direction_accuracy", new=AsyncMock(return_value={"name": "forecast_direction_accuracy", "status": "passed"})):
                                with patch("app.services.health.reporter.check_orderbook_ws_liveness", new=AsyncMock(return_value={"name": "orderbook_ws_liveness", "status": "passed"})):
                                    with patch("app.services.health.reporter.check_terminal_widget_latency", new=AsyncMock(return_value={"name": "terminal_widget_latency", "status": "passed"})):
                                        with patch("app.services.health.reporter.apply_remediations", new=AsyncMock(return_value=[])):
                                            report = await run_health_report(send_telegram=False)
    names = [r["name"] for r in report["results"]]
    assert "aitunnel_token_balance" in names
