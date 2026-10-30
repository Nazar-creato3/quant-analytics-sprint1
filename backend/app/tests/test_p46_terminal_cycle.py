from __future__ import annotations

from app.services.context_cycle.service import aligned_numbers, cycle_hrefs
from app.services.qa.feature_flags import reset_for_tests


def setup_function() -> None:
    reset_for_tests()


def teardown_function() -> None:
    reset_for_tests()


def test_cycle_hrefs_share_ticker_query():
    hrefs = cycle_hrefs("sber")
    assert hrefs["ticker"] == "SBER"
    assert "symbol=SBER" in hrefs["portfolio_impact"]
    assert hrefs["pretrade"].endswith("symbol=SBER")
    assert hrefs["maneuvers"].endswith("symbol=SBER")
    assert hrefs["risk_events"].endswith("symbol=SBER")


def test_report_var_matches_risk_engine():
    payload = aligned_numbers(user_id="cycle-user", mode="paper")
    assert payload["var_95_risk"] == payload["var_95_report"]
    assert payload["var_95_risk"] == payload["var_95_first_screen"]
    assert payload["source_risk"] == "risk_engine"
    assert payload["source_report"] == "portfolio_report"
