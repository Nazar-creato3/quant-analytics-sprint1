"""Tests for agentic in-app chat upgrade."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.chat.mode_router import ChatMode, classify_chat_mode
from app.services.chat.quality_eval import QUALITY_EVAL_QUESTIONS
from app.services.chat.tools import TOOL_SCHEMAS
from app.services.chat.swarm import needs_swarm


class TestModeRouter:
    def test_simple_price_is_instant(self):
        assert classify_chat_mode("какая цена у SBER") == ChatMode.INSTANT

    def test_complex_is_thinking(self):
        assert classify_chat_mode(
            "стоит ли пересматривать позицию в нефтянке с учётом последних новостей по санкциям"
        ) == ChatMode.THINKING

    def test_compare_is_thinking(self):
        assert classify_chat_mode("сравни SBER и VTBR по факторам") == ChatMode.THINKING


class TestToolSchemas:
    def test_all_plan_tools_defined(self):
        names = {t["function"]["name"] for t in TOOL_SCHEMAS}
        expected = {
            "get_factor_exposures",
            "get_shap_explanation",
            "get_risk_metrics",
            "get_recent_news",
            "compare_tickers",
            "get_market_regime",
            "get_macro_context",
            "get_dividend_data",
            "get_current_forecast",
            "get_portfolio_risk_metrics",
            "get_position_pnl",
            "search_instruments",
        }
        assert expected.issubset(names)

    def test_schemas_are_valid_json_shape(self):
        for tool in TOOL_SCHEMAS:
            assert tool["type"] == "function"
            assert "name" in tool["function"]
            assert "parameters" in tool["function"]


class TestSwarm:
    def test_portfolio_triggers_swarm(self):
        assert needs_swarm("проанализируй весь мой портфель и скажи где риски")

    def test_simple_does_not_trigger(self):
        assert not needs_swarm("какая цена у AAPL")


class TestQualityEvalCorpus:
    def test_corpus_size(self):
        assert len(QUALITY_EVAL_QUESTIONS) >= 30

    def test_categories_represented(self):
        joined = " ".join(QUALITY_EVAL_QUESTIONS).lower()
        assert "сравни" in joined or "compare" in joined
        assert "портфел" in joined or "portfolio" in joined
        assert "макро" in joined or "macro" in joined


class TestAgenticPrompt:
    def test_build_agentic_system(self):
        from app.services.chat.advisor_prompt import build_agentic_chat_system

        sys = build_agentic_chat_system(mode="thinking")
        assert "ANTI-TEMPLATE" in sys
        assert "function calling" in sys.lower() or "TOOLS" in sys
        assert "is_valid=false" in sys.lower()
        assert "get_portfolio_risk_metrics" in sys
        assert "never invent" in sys.lower() or "не выдумывай" in sys.lower() or "fabrication" in sys.lower()


class TestToolStamp:
    @pytest.mark.asyncio
    async def test_unknown_tool_does_not_fabricate(self):
        import json

        from app.services.chat.tools import execute_tool

        raw = await execute_tool(AsyncMock(), "not_a_real_tool", {})
        payload = json.loads(raw)
        assert payload["data_available"] is False
        assert payload["fabrication_forbidden"] is True
        assert payload["tool"] == "not_a_real_tool"
        assert payload["tool_called_at"]
        assert "error" in payload


class TestChatToolProof:
    @pytest.mark.asyncio
    async def test_position_question_calls_tools_with_citations(self):
        import json

        from app.services.chat.tools import execute_tool

        db = AsyncMock()
        risk_payload = {
            "var_95": 0.023,
            "methodology": {"method_ru": "Историческая симуляция"},
            "data_as_of": "2026-08-21T18:00:00+00:00",
        }
        pnl_payload = {
            "ticker": "AAPL",
            "unrealized_pnl_usd": 100.0,
            "data_as_of": "2026-08-21T18:00:00+00:00",
        }
        with patch("app.services.chat.tools._tool_portfolio_risk", new_callable=AsyncMock) as mock_risk:
            mock_risk.return_value = risk_payload
            raw = await execute_tool(db, "get_portfolio_risk_metrics", {}, owner_email="u@test.com")
        risk = json.loads(raw)
        assert risk["tool"] == "get_portfolio_risk_metrics"
        assert risk["data_as_of"]
        assert risk["data_available"] is True

        with patch("app.services.chat.tools._tool_position_pnl", new_callable=AsyncMock) as mock_pnl:
            mock_pnl.return_value = pnl_payload
            raw_pnl = await execute_tool(db, "get_position_pnl", {"ticker": "AAPL"}, owner_email="u@test.com")
        pnl = json.loads(raw_pnl)
        assert pnl["tool"] == "get_position_pnl"
        assert pnl["ticker"] == "AAPL"


class TestRecoveryHardening:
    @pytest.mark.asyncio
    async def test_expired_token_triggers_security_audit(self):
        from app.services.auth.recovery import reset_password_with_token

        db = AsyncMock()
        token_row = MagicMock()
        token_row.user_id = "u1"
        token_row.token_hash = "abc"
        token_row.used_at = None
        token_row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=5)

        with patch("app.services.auth.recovery.hash_token", return_value="abc"):
            with patch("app.services.auth.recovery.verify_token_hash", return_value=True):
                with patch("app.services.auth.recovery.is_expired", return_value=True):
                    with patch(
                        "app.services.auth.recovery._alert_suspicious_recovery_attempt",
                        new=AsyncMock(),
                    ) as mock_alert:
                        db.execute = AsyncMock(
                            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=token_row))
                        )
                        ok = await reset_password_with_token(
                            db,
                            raw_token="token",
                            new_password="NewSecurePass1!",
                            ip="1.2.3.4",
                            user_agent="test",
                        )
        assert ok is False
        mock_alert.assert_awaited_once()
