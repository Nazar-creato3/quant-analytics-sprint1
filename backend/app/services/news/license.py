"""News source licenses — same tags as Prompt 04, separate JSON (Prompt 44)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from app.services.market_data.license import LicenseTag, may_display

_POLICY = Path(__file__).with_name("news_license.json")

Audience = Literal["owner", "public", "internal"]


def load_news_policy() -> dict[str, LicenseTag]:
    return json.loads(_POLICY.read_text(encoding="utf-8"))


def tag_for_news_source(source: str) -> LicenseTag:
    policy = load_news_policy()
    return policy.get((source or "").strip().lower(), "internal_only")  # type: ignore[return-value]


def may_store(source: str) -> bool:
    return tag_for_news_source(source) != "forbidden"


def may_show(source: str, *, audience: Audience = "internal") -> bool:
    return may_display(tag_for_news_source(source), audience=audience)


_FETCH: dict[str, tuple[str, str]] = {
    "rbc": ("rss", "ingest_news_task"),
    "interfax": ("rss", "ingest_news_task"),
    "investing_com": ("rss", "ingest_news_task"),
    "newsapi": ("http_api", "ingest_news_task"),
    "gnews": ("http_api", "free_feeds"),
    "newscatcher": ("http_api", "free_feeds"),
    "gdelt": ("http_api", "free_feeds"),
    "cryptopanic": ("http_api", "free_feeds"),
    "finimpulse": ("http_api", "free_feeds"),
    "archive_unlicensed": ("legacy_archive", "manual"),
    "financial_csv_dataset": ("csv", "import_csv_news"),
}


def source_catalog() -> list[dict[str, str]]:
    """License matrix 04 tags + fetch method. Unknown keys stay internal_only."""
    policy = load_news_policy()
    rows: list[dict[str, str]] = []
    for source, tag in sorted(policy.items()):
        method, freq = _FETCH.get(source, ("unknown", "manual"))
        rows.append(
            {
                "source": source,
                "license_tag": tag,
                "method": method,
                "frequency": freq,
                "may_store": str(tag != "forbidden").lower(),
            }
        )
    return rows
