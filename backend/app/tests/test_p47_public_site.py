"""Prompt 47: public pages keep unset copy unpublished."""
from __future__ import annotations

from pathlib import Path

from app.services.qa.feature_flags import is_enabled, reset_for_tests

FORBIDDEN = ("рекомендуем", "советуем", "подходит вам", "соответствует вашему профилю", "купите", "продайте")
TRACKERS = ("google-analytics", "googletagmanager", "metrika", "facebook.net", "hotjar")
FILES = (
    "frontend/src/lib/public-site.ts",
    "frontend/src/components/site/PublicSiteHome.tsx",
    "frontend/src/components/site/LegalSlot.tsx",
    "frontend/src/app/sitemap.ts",
    "frontend/src/app/robots.ts",
    "frontend/src/app/site/page.tsx",
    "frontend/src/app/site/accuracy/page.tsx",
    "frontend/src/app/methodology/page.tsx",
)


def setup_function() -> None:
    reset_for_tests()


def test_live_flag_stays_off() -> None:
    assert is_enabled("qa_act_live") is False


def test_public_copy_is_unpublished_and_has_no_tracker() -> None:
    root = Path(__file__).resolve().parents[3]
    blob = []
    for rel in FILES:
        text = (root / rel).read_text(encoding="utf-8")
        blob.append(text.lower())
        assert 'from "@/lib/api"' not in text
        assert "from '@/lib/api'" not in text
    joined = "\n".join(blob)
    for phrase in FORBIDDEN:
        assert phrase not in joined
    for tracker in TRACKERS:
        assert tracker not in joined
    copy = (root / "frontend/src/lib/public-site.ts").read_text(encoding="utf-8")
    assert "Опубликованная точность: нет данных." in copy
    assert "ожидает текста" in copy
    assert '"/site"' in copy
    assert "/account" not in copy
    sitemap = (root / "frontend/src/app/sitemap.ts").read_text(encoding="utf-8")
    assert "PUBLIC_SITEMAP_PATHS" in sitemap
    assert "/account" not in sitemap
    middleware = (root / "frontend/src/middleware.ts").read_text(encoding="utf-8")
    assert '"/site"' in middleware
    assert '"/methodology"' in middleware
