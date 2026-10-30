"""The chat answer never names the language model or its vendor (no technical info in the UI)."""
from __future__ import annotations

from app.services.chat import deep_advisor


def test_chat_footer_has_no_model_name() -> None:
    for text in (deep_advisor.CHAT_SOURCE_LLM_RU, deep_advisor.CHAT_SOURCE_RULE_RU):
        low = text.lower()
        assert "kimi" not in low
        assert "llm" not in low
        assert "shap" not in low
