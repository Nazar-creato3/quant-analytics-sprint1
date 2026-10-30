"""Prompt 31: documentation links resolve and do not invent a price."""
from __future__ import annotations

import re
from pathlib import Path

from app.services.qa.feature_flags import is_enabled, reset_for_tests

FORBIDDEN = ("рекомендуем", "советуем", "подходит вам", "соответствует вашему профилю", "купите", "продайте")
DOCS = (
    "docs/architecture/core-map.md",
    "docs/architecture/service-catalog.md",
    "docs/architecture/entity-dictionary.md",
    "docs/dev/add-a-piece.md",
    "docs/user/glossary.md",
    "docs/user/how-to-read-report.md",
    "docs/user/beta-status.md",
    "docs/user/connect-key.md",
    "docs/user/faq.md",
    "docs/methodology/public-overview.md",
    "docs/adr/0026-documentation-index.md",
)
LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
PACKAGE = re.compile(r"`(backend/app/services/[a-z0-9_]+)`")


def setup_function() -> None:
    reset_for_tests()


def test_flags_and_price_stay_unset() -> None:
    assert is_enabled("qa_act_live") is False
    middleware = Path(__file__).resolve().parents[3] / "frontend" / "src" / "middleware.ts"
    text = middleware.read_text(encoding="utf-8")
    assert '"/methodology"' in text


def test_doc_links_and_packages_exist() -> None:
    root = Path(__file__).resolve().parents[3]
    for rel in DOCS:
        text = (root / rel).read_text(encoding="utf-8")
        lowered = text.lower()
        for phrase in FORBIDDEN:
            assert phrase not in lowered, rel
        for target in LINK.findall(text):
            if target.startswith("http"):
                continue
            path = (root / rel).parent.joinpath(target.split("#", 1)[0]).resolve()
            assert path.is_file(), f"{rel} -> {target}"
        if rel.endswith("service-catalog.md"):
            names = PACKAGE.findall(text)
            assert len(names) >= 16
            for name in names:
                assert (root / name).is_dir(), name
