"""Tests for region-aware macro snippets."""
from app.services.analysis.macro_region import format_macro_snippet_for_symbol


def test_spy_uses_fed_rate_not_cbr():
    snippet = format_macro_snippet_for_symbol(
        "SPY",
        {"rate_cb": 14.25, "rate_cb_us": 3.75, "vix": 17.0, "cpi": 3.5},
    )
    assert "3.75" in snippet
    assert "ФРС" in snippet
    assert "14.25" not in snippet
    assert "ЦБ РФ" not in snippet


def test_multi_region_summaries_do_not_cross_contaminate():
    us = format_macro_snippet_for_symbol(
        "SPY",
        {"rate_cb": 14.25, "rate_cb_us": 3.75, "vix": 17.0},
    )
    ru = format_macro_snippet_for_symbol(
        "GAZP",
        {"rate_cb": 14.25, "rate_cb_us": 3.75, "vix": 17.0},
    )
    assert "14.25" not in us
    assert "3.75" not in ru
    assert "ФРС" in us
    assert "ЦБ РФ" in ru


def test_gazp_uses_cbr_rate():
    snippet = format_macro_snippet_for_symbol(
        "GAZP",
        {"rate_cb": 14.25, "rate_cb_us": 3.75, "vix": 17.0},
    )
    assert "14.25" in snippet
    assert "ЦБ РФ" in snippet
    assert "ФРС" not in snippet

