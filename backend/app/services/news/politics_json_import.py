"""Bulk import of Webz.io-style political news JSON datasets into ``news_articles``."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import NewsArticle
from app.services.news.client import extract_tickers_from_text, score_sentiment_vader
from app.services.news.csv_bulk_import import CsvImportStats, default_news_csv_dir
from app.services.news.filtering import compute_market_relevance

logger = get_logger(__name__)

POLITICS_JSON_SOURCE = "politics_json_dataset"
SYNTHETIC_URL_PREFIX = "csv://politics/"

_POLITICS_DIR_RE = re.compile(
    r"^Politics_(positive|negative)(?:[_-].*)?$",
    re.IGNORECASE,
)

_FOLDER_SENTIMENT: dict[str, tuple[str, float]] = {
    "positive": ("positive", 1.0),
    "negative": ("negative", -1.0),
}


@dataclass(frozen=True, slots=True)
class ParsedPoliticsRow:
    title: str
    content: str
    description: str | None
    published_at: datetime
    sentiment_score: float
    sentiment_label: str
    tickers_mentioned: list[str]
    url: str
    extracted_events: list[dict[str, Any]]
    relevance_score: float


def discover_politics_dirs(data_dir: Path) -> list[tuple[Path, str, float]]:
    """Return ``(directory, sentiment_label, sentiment_score)`` for Politics_* folders."""
    data_dir = data_dir.expanduser().resolve()
    if not data_dir.is_dir():
        return []

    discovered: list[tuple[Path, str, float]] = []
    for child in sorted(data_dir.iterdir()):
        if not child.is_dir():
            continue
        match = _POLITICS_DIR_RE.match(child.name)
        if not match:
            continue
        label, score = _FOLDER_SENTIMENT[match.group(1).lower()]
        discovered.append((child, label, score))
    return discovered


def politics_dirs_present(data_dir: Path) -> bool:
    return bool(discover_politics_dirs(data_dir))


def content_hash(*parts: str) -> str:
    normalized = "|".join(re.sub(r"\s+", " ", part.strip().lower()) for part in parts if part)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]


def synthetic_politics_url(*parts: str) -> str:
    return f"{SYNTHETIC_URL_PREFIX}{content_hash(*parts)}"


def _parse_published_at(raw: Any, *, fallback: datetime) -> datetime:
    if not raw:
        return fallback
    text = str(raw).strip()
    if not text:
        return fallback
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return fallback
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _extract_post_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []

    posts = payload.get("posts")
    if isinstance(posts, list):
        return [item for item in posts if isinstance(item, dict)]

    if any(key in payload for key in ("text", "title", "thread", "uuid")):
        return [payload]
    return []


def _post_fields(
    post: dict[str, Any],
    *,
    folder_label: str,
    folder_score: float,
    reference: datetime,
) -> ParsedPoliticsRow | None:
    thread = post.get("thread") if isinstance(post.get("thread"), dict) else {}

    title = (
        post.get("title")
        or thread.get("title")
        or thread.get("title_full")
        or post.get("highlightTitle")
        or ""
    )
    title = str(title).strip()
    if not title:
        return None

    content = str(
        post.get("text")
        or post.get("content")
        or post.get("body")
        or thread.get("text")
        or ""
    ).strip()

    published_raw = post.get("published") or thread.get("published") or post.get("crawled")
    published_at = _parse_published_at(published_raw, fallback=reference)

    site = str(thread.get("site") or thread.get("site_full") or "").strip()
    categories = post.get("categories") or thread.get("categories") or []
    if isinstance(categories, list):
        category_text = ", ".join(str(item).strip() for item in categories if str(item).strip())
    else:
        category_text = str(categories).strip() if categories else ""

    description_parts = [part for part in (site, category_text or "Politics") if part]
    description = " · ".join(description_parts) if description_parts else "Politics"

    body = f"{title} {content}".strip()
    vader_score, vader_label = score_sentiment_vader(body)
    sentiment_label = folder_label
    sentiment_score = folder_score
    if folder_label == "positive" and vader_score < -0.2:
        sentiment_score = max(folder_score, vader_score)
    elif folder_label == "negative" and vader_score > 0.2:
        sentiment_score = min(folder_score, vader_score)

    tickers = extract_tickers_from_text(body)
    relevance = max(compute_market_relevance(body), 0.45 if tickers else 0.35)

    uuid = str(post.get("uuid") or thread.get("uuid") or "").strip()
    url_key = uuid or title
    synthetic = synthetic_politics_url(url_key, published_at.isoformat())

    extracted_events: list[dict[str, Any]] = [
        {
            "event_type": "macro",
            "tag": "politics",
            "category": category_text or "Politics",
            "market_effect": sentiment_label,
            "confidence": round(abs(sentiment_score), 3),
            "vader_label": vader_label,
        }
    ]

    return ParsedPoliticsRow(
        title=title[:1000],
        content=content[:8000] if content else "",
        description=description,
        published_at=published_at,
        sentiment_score=round(float(sentiment_score), 4),
        sentiment_label=sentiment_label,
        tickers_mentioned=tickers,
        url=synthetic,
        extracted_events=extracted_events,
        relevance_score=round(relevance, 3),
    )


def iter_politics_json_rows(
    politics_dir: Path,
    *,
    folder_label: str,
    folder_score: float,
    reference: datetime,
) -> Iterable[ParsedPoliticsRow]:
    for json_path in sorted(politics_dir.rglob("*.json")):
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Skipping invalid politics JSON", path=str(json_path), error=str(exc))
            continue

        for post in _extract_post_records(payload):
            parsed = _post_fields(
                post,
                folder_label=folder_label,
                folder_score=folder_score,
                reference=reference,
            )
            if parsed is not None:
                yield parsed


async def import_politics_json_news(
    db: AsyncSession,
    data_dir: Path | str | None = None,
    *,
    reference: datetime | None = None,
    dry_run: bool = False,
    limit: int | None = None,
    commit_batch_size: int = 500,
) -> CsvImportStats:
    """Idempotent bulk import — skips rows whose synthetic URL already exists."""
    stats = CsvImportStats()
    root = Path(data_dir).expanduser().resolve() if data_dir is not None else default_news_csv_dir()
    ref = reference or datetime.now(timezone.utc)
    seen_urls: set[str] = set()
    pending = 0

    politics_dirs = discover_politics_dirs(root)
    if not politics_dirs:
        logger.info("No Politics_* directories found", path=str(root))
        return stats

    for politics_dir, folder_label, folder_score in politics_dirs:
        stats.files_seen += 1
        for parsed in iter_politics_json_rows(
            politics_dir,
            folder_label=folder_label,
            folder_score=folder_score,
            reference=ref,
        ):
            if parsed.url in seen_urls:
                stats.skipped_duplicate += 1
                continue
            seen_urls.add(parsed.url)
            stats.rows_parsed += 1

            if limit is not None and stats.rows_parsed > limit:
                break

            if dry_run:
                stats.inserted += 1
                continue

            existing = await db.execute(
                select(NewsArticle.id).where(NewsArticle.url == parsed.url)
            )
            if existing.scalar_one_or_none():
                stats.skipped_duplicate += 1
                continue

            db.add(
                NewsArticle(
                    title=parsed.title,
                    description=parsed.description,
                    content=parsed.content or None,
                    url=parsed.url,
                    source=POLITICS_JSON_SOURCE,
                    published_at=parsed.published_at,
                    sentiment_score=parsed.sentiment_score,
                    sentiment_label=parsed.sentiment_label,
                    tickers_mentioned=parsed.tickers_mentioned,
                    extracted_events=parsed.extracted_events,
                    relevance_score=parsed.relevance_score,
                )
            )
            stats.inserted += 1
            pending += 1

            if pending >= commit_batch_size:
                try:
                    await db.commit()
                except Exception as exc:
                    await db.rollback()
                    stats.errors.append(str(exc))
                    logger.warning("Politics JSON batch commit failed", error=str(exc))
                pending = 0

        if limit is not None and stats.rows_parsed >= limit:
            break

    if not dry_run and pending:
        try:
            await db.commit()
        except Exception as exc:
            await db.rollback()
            stats.errors.append(str(exc))
            logger.warning("Politics JSON final commit failed", error=str(exc))

    logger.info(
        "Politics JSON import finished",
        dirs=stats.files_seen,
        parsed=stats.rows_parsed,
        inserted=stats.inserted,
        skipped=stats.skipped_duplicate,
        dry_run=dry_run,
    )
    return stats
