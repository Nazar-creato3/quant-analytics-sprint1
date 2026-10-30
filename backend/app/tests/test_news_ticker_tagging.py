"""News must be tagged only with tickers the text really mentions."""
from __future__ import annotations

from datetime import datetime, timezone

from app.schemas.schemas import NewsArticleOut
from app.services.news.client import clean_mentions, extract_tickers_from_text, text_matches_ticker


def test_unrelated_story_is_not_tagged_with_query_ticker():
    text = "Pharma Mar на конференции представила данные по препарату"
    assert not text_matches_ticker(text, "GAZP")
    assert clean_mentions(text, ["GAZP"]) == []


def test_real_mentions_kept_in_order():
    text = "Газпром и Сбербанк: дивиденды; NVIDIA растёт"
    assert clean_mentions(text, ["GAZP", "SBER", "NVDA", "AAPL"]) == ["GAZP", "SBER", "NVDA"]


def test_cyrillic_word_boundary():
    assert not text_matches_ticker("Сбережения граждан выросли", "SBER")
    assert text_matches_ticker("СБЕР отчитался", "SBER")


def test_short_tickers_need_capitals_or_cashtag():
    assert not text_matches_ticker("He met a friend at the station", "T")
    assert not text_matches_ticker("ma and pa shops", "MA")
    assert text_matches_ticker("Shares of $T rose", "T")
    assert text_matches_ticker("Visa (V) and Mastercard (MA) report", "MA")
    assert "MA" not in extract_tickers_from_text("Mastercard (MA) report")  # bare 2-letter is not auto-extracted
    assert extract_tickers_from_text("NVDA and $MA up") == ["MA", "NVDA"]


def test_meta_does_not_hit_metals():
    assert not text_matches_ticker("Precious METALS rally", "META")


def test_api_output_drops_stale_force_tags():
    row = NewsArticleOut(
        id="1",
        title="Pharma Mar на конференции",
        url="https://x",
        source="investing_com",
        published_at=datetime(2026, 10, 20, tzinfo=timezone.utc),
        tickers_mentioned=["GAZP"],
    )
    assert row.tickers_mentioned == []
