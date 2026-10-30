"""Regression: no cross-ticker fact leakage in one chat session (Prompt 80)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.chat.context_isolation import (
    prior_messages_for_symbol,
    resolve_advisor_symbol,
)


def test_resolve_advisor_symbol_prefers_explicit_ticker_in_question():
    assert resolve_advisor_symbol("GOOGL outlook for Q3", "GAZP") == "GOOGL"
    assert resolve_advisor_symbol("outlook", "GAZP") == "GAZP"
    assert resolve_advisor_symbol("AMZN risk", None) == "AMZN"


def test_prior_messages_drop_gazp_invest_program_for_googl():
    gazp_prior = (
        "GAZP: инвестпрограмма 515 млрд ₽ на 2025–2027; ключевой драйвер CAPEX.",
    )
    filtered = prior_messages_for_symbol(gazp_prior, "GOOGL")
    assert filtered == ()


def test_prior_messages_keep_same_ticker_history():
    prior = ("GOOGL: выручка растёт, P/E в норме.",)
    assert prior_messages_for_symbol(prior, "GOOGL") == prior
