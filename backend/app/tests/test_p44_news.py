from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.services.news.compare import compare_event_models
from app.services.news.labeled import labeled_news
from app.services.news.license import may_show, may_store, source_catalog, tag_for_news_source
from app.services.news.pipeline import ingest_batch, is_near_duplicate, latency_seconds, process_article
from app.services.pit.news_events import taxonomy_features

REPO = Path(__file__).resolve().parents[3]


def test_news_license_rss_internal_until_letter():
    assert tag_for_news_source("rbc") == "internal_only"
    assert may_store("rbc") is True
    assert may_show("rbc", audience="public") is False
    assert may_show("rbc", audience="internal") is True
    assert may_store("archive_unlicensed") is True
    assert may_show("archive_unlicensed", audience="public") is False
    names = {row["source"] for row in source_catalog()}
    assert {"rbc", "interfax", "financial_csv_dataset", "newsapi"} <= names


def test_labeled_set_at_least_500():
    rows = labeled_news(500)
    assert len(rows) == 500
    events = {r["event"] for r in rows}
    assert "dividend" in events and "sanctions" in events and "cbr" in events


def test_near_dup_and_entity_link():
    assert is_near_duplicate(
        "Сбербанк объявил дивиденды 10 руб на акцию",
        "Сбербанк объявил дивиденды 10 руб на акцию сегодня",
    )
    item = process_article(
        {
            "title": "Сбербанк объявил дивиденды 12 руб на акцию",
            "source": "rbc",
            "published_at": "2026-10-01T12:00:00+00:00",
        },
        audience="internal",
        now=datetime(2026, 10, 1, 12, 5, tzinfo=timezone.utc),
    )
    assert item is not None
    assert "SBER" in item["tickers"]
    assert item["event"] == "dividend"
    assert item["latency_sec"] == 300


def test_public_hides_internal_rss_title():
    item = process_article(
        {"title": "Секрет", "source": "interfax", "published_at": "2026-10-01T00:00:00+00:00"},
        audience="public",
    )
    assert item is not None
    assert item["title"] is None
    assert item["display_allowed"] is False


def test_ingest_drops_near_duplicates():
    rows = [
        {"title": "Яндекс объявил слияние, сделка номер 1", "source": "rbc"},
        {"title": "Яндекс объявил слияние, сделка номер 1", "source": "rbc"},
    ]
    out = ingest_batch(rows)
    assert len(out) == 1


def test_pit_drops_lookahead_articles():
    arts = [
        {
            "knowledge_time": datetime(2026, 1, 10, tzinfo=timezone.utc),
            "taxonomy": "earnings",
            "polarity": 0.1,
        },
        {
            "knowledge_time": datetime(2026, 2, 1, tzinfo=timezone.utc),
            "taxonomy": "earnings",
            "polarity": 0.9,
        },
    ]
    feats = taxonomy_features(arts, as_of=datetime(2026, 1, 15, tzinfo=timezone.utc))
    assert feats["earnings"] == 1.0


def test_model_compare_and_latency_budget():
    report = compare_event_models(n=500)
    assert report["n"] == 500
    assert report["dictionary_f1"] >= 0.5
    assert report["ticker_link_accuracy"] >= 0.5
    assert report["chosen"] in {"dictionary", "naive_bayes"}
    budget = json.loads((REPO / "docs" / "qa" / "perf-budgets.json").read_text(encoding="utf-8"))
    max_lag = float(budget["news_show_lag_sec"]["max"])
    published = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
    shown = published + timedelta(seconds=90)
    assert latency_seconds(published_at=published, shown_at=shown) < max_lag
    text = (REPO / "docs" / "models" / "news.md").read_text(encoding="utf-8")
    assert "F1" in text
