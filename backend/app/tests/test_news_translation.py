"""Tests for news RU machine translation layer."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.db.models import NewsArticle
from app.services.news.translation import (
    _cyrillic_ratio,
    _is_russian_source,
    localize_news_article,
)


def test_cyrillic_ratio_detects_russian():
    assert _cyrillic_ratio("Сбербанк повысил ставку") > 0.5
    assert _cyrillic_ratio("Fed raises rates") < 0.2


def test_russian_source_detection():
    assert _is_russian_source("RBC Economics")
    assert not _is_russian_source("Reuters")


@pytest.mark.asyncio
async def test_localize_skips_mt_for_russian_source():
    article = NewsArticle(
        id="n1",
        title="ЦБ сохранил ключевую ставку",
        description="Краткий обзор",
        url="https://example.com/1",
        source="RBC",
        published_at=datetime.now(timezone.utc),
    )
    out = await localize_news_article(article, locale="ru")
    assert out.title_ru == article.title
    assert out.is_machine_translated is False


@pytest.mark.asyncio
async def test_localize_uses_cache_for_english_article():
    article = NewsArticle(
        id="n2",
        title="Apple beats earnings expectations",
        description="Strong iPhone sales drive revenue",
        url="https://example.com/2",
        source="Reuters",
        published_at=datetime.now(timezone.utc),
    )
    with patch(
        "app.services.news.translation.cache_get",
        new=AsyncMock(
            return_value={
                "title_ru": "Apple превзошла ожидания по прибыли",
                "summary_ru": "Сильные продажи iPhone",
                "is_machine_translated": True,
            }
        ),
    ):
        out = await localize_news_article(article, locale="ru")

    assert out.title_ru == "Apple превзошла ожидания по прибыли"
    assert out.is_machine_translated is True


@pytest.mark.asyncio
async def test_localize_en_locale_returns_original():
    article = NewsArticle(
        id="n3",
        title="Market update",
        description="Brief",
        url="https://example.com/3",
        source="Bloomberg",
        published_at=datetime.now(timezone.utc),
    )
    out = await localize_news_article(article, locale="en")
    assert out.title == "Market update"
    assert out.title_ru is None
    assert out.is_machine_translated is False
