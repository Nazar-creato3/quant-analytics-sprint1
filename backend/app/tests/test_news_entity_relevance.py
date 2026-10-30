"""Entity-aware news bucketing for chat (GAZP noise rejection)."""
from __future__ import annotations

from app.services.chat.advisor_prompt import _bucket_headlines_for_display
from app.services.news.entity_relevance import bucket_headline, entity_relevance_score


def test_gazp_noise_headline_not_corporate():
    title = "India paper leaks spark debate; Uganda travel advisory updated"
    assert bucket_headline(title, ticker="GAZP") == "other"
    assert entity_relevance_score(title, "GAZP").score < 0.2


def test_gazp_jd_vance_noise_not_corporate():
    title = "JD Vance comments on India trade policy spark debate"
    assert bucket_headline(title, ticker="GAZP") == "other"
    assert entity_relevance_score(title, "GAZP").score < 0.2


def test_lkoh_treasury_license_headline_matches():
    title = "US Treasury extends license for Lukoil International GmbH; Carlyle talks cited"
    match = entity_relevance_score(title, "LKOH")
    assert match.score >= 0.72
    assert bucket_headline(title, ticker="LKOH") == "corporate"


def test_gazprom_alias_is_corporate():
    title = "Газпром обсуждает новые условия поставок газа в Европу"
    assert bucket_headline(title, ticker="GAZP") == "corporate"


def test_bucket_display_separates_corporate_and_other():
    titles = (
        "Газпром reports pipeline maintenance schedule",
        "India paper leaks spark debate",
        "Fed signals rates unchanged",
    )
    corp, ext, other = _bucket_headlines_for_display(titles, cap=10, ticker="GAZP")
    assert any("Gazprom" in t or "Газпром" in t for t in corp)
    assert not any("India" in t for t in corp)
    assert any("India" in t for t in other)
