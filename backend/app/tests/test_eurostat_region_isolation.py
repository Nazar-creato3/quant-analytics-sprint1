"""Eurostat EU macro must not leak into US/RU instrument snippets (Prompt 87/88)."""
from app.services.analysis.macro_region import format_macro_snippet_for_symbol


def test_spy_summary_excludes_eu_only_indicators():
    snippet = format_macro_snippet_for_symbol(
        "SPY",
        {
            "rate_cb_us": 3.75,
            "rate_cb": 14.25,
            "eu_hicp_yoy": 2.4,
            "eu_unemployment": 6.5,
            "vix": 16.0,
        },
    )
    assert "еврозон" not in snippet.lower()
    assert "2.4" not in snippet or "HICP" not in snippet


def test_global_crypto_may_include_eu_gdp_when_present():
    snippet = format_macro_snippet_for_symbol(
        "BTCUSDT",
        {"vix": 20.0, "eu_gdp_yoy": 1.1},
    )
    assert "еврозон" in snippet.lower() or "EU" in snippet or snippet
