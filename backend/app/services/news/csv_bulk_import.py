"""Bulk import of financial news CSV datasets into ``news_articles``."""
from __future__ import annotations

import csv
import hashlib
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import NewsArticle
from app.services.news.client import (
    _compute_relevance,
    extract_tickers_from_text,
    score_sentiment_vader,
)
from app.services.news.filtering import compute_market_relevance
from app.services.news.license import may_store

logger = get_logger(__name__)

CSV_SOURCE = "financial_csv_dataset"
SYNTHETIC_URL_PREFIX = "csv://financial-dataset/"

# Prefer categorized + sentiment-named exports; skip duplicates from sibling files.
_CSV_PRIORITY: tuple[str, ...] = (
    "Financial_Sentiment_Categorized.csv",
    "Financial_Categorized.csv",
    "Financial_Sentiment.csv",
    "Financial.csv",
)

_TAIL_DAY_RE = re.compile(r"(\d)\s*days?\s+ago\s*$", re.IGNORECASE)

_RELATIVE_DATE_RE = re.compile(
    r"(\d{1,3})\s*(seconds?|minutes?|hours?|days?|weeks?|months?|years?)\s+ago",
    re.IGNORECASE,
)

_UNIT_TO_DELTA: dict[str, Callable[[int], timedelta]] = {
    "second": lambda n: timedelta(seconds=n),
    "seconds": lambda n: timedelta(seconds=n),
    "minute": lambda n: timedelta(minutes=n),
    "minutes": lambda n: timedelta(minutes=n),
    "hour": lambda n: timedelta(hours=n),
    "hours": lambda n: timedelta(hours=n),
    "day": lambda n: timedelta(days=n),
    "days": lambda n: timedelta(days=n),
    "week": lambda n: timedelta(weeks=n),
    "weeks": lambda n: timedelta(weeks=n),
    "month": lambda n: timedelta(days=n * 30),
    "months": lambda n: timedelta(days=n * 30),
    "year": lambda n: timedelta(days=n * 365),
    "years": lambda n: timedelta(days=n * 365),
}


@dataclass(slots=True)
class CsvImportStats:
    files_seen: int = 0
    rows_parsed: int = 0
    inserted: int = 0
    skipped_duplicate: int = 0
    skipped_invalid: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ParsedNewsRow:
    title: str
    tag: str
    content: str
    category: str | None
    published_at: datetime
    sentiment_score: float
    sentiment_label: str
    tickers_mentioned: list[str]
    url: str
    description: str | None
    extracted_events: list[dict[str, Any]]
    relevance_score: float


def default_news_csv_dir() -> Path:
    from app.core.config import settings

    return Path(settings.NEWS_CSV_DATA_DIR).expanduser()


def prepare_data_directory(data_dir: Path) -> Path:
    """Extract ``*.zip`` archives in place (idempotent) and return the directory."""
    data_dir = data_dir.expanduser().resolve()
    if not data_dir.is_dir():
        raise FileNotFoundError(f"News CSV directory not found: {data_dir}")

    for zip_path in sorted(data_dir.glob("*.zip")):
        try:
            with zipfile.ZipFile(zip_path) as archive:
                csv_members = [name for name in archive.namelist() if name.lower().endswith(".csv")]
                if csv_members and all((data_dir / Path(name).name).exists() for name in csv_members):
                    continue
                archive.extractall(data_dir)
            logger.info("Extracted news CSV zip", path=str(zip_path))
        except zipfile.BadZipFile as exc:
            logger.warning("Skipping invalid zip", path=str(zip_path), error=str(exc))
    return data_dir


def discover_csv_files(data_dir: Path) -> list[Path]:
    """Return CSV files to import, de-duplicated by priority."""
    data_dir = prepare_data_directory(data_dir)
    available = {path.name: path for path in data_dir.glob("*.csv")}
    ordered: list[Path] = []
    for name in _CSV_PRIORITY:
        if name in available:
            ordered.append(available[name])
    for name, path in sorted(available.items()):
        if path not in ordered:
            ordered.append(path)
    return ordered


def title_hash(title: str) -> str:
    normalized = re.sub(r"\s+", " ", title.strip().lower())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]


def synthetic_url(title: str) -> str:
    return f"{SYNTHETIC_URL_PREFIX}{title_hash(title)}"


def parse_relative_published_at(
    text: str,
    *,
    reference: datetime | None = None,
) -> datetime:
    """Parse trailing ``N days ago`` fragments; fall back to reference time."""
    ref = reference or datetime.now(timezone.utc)
    stripped = (text or "").rstrip()

    tail_day = _TAIL_DAY_RE.search(stripped)
    if tail_day:
        return ref - timedelta(days=int(tail_day.group(1)))

    matches = list(_RELATIVE_DATE_RE.finditer(stripped))
    if not matches:
        return ref

    def _match_key(match: re.Match[str]) -> tuple[int, int, int]:
        amount = int(match.group(1))
        unit = match.group(2).lower()
        at_end = match.end() >= len(stripped)
        day_bias = -amount if unit.startswith("day") else 0
        return (1 if at_end else 0, day_bias, match.start())

    match = max(matches, key=_match_key)
    amount = int(match.group(1))
    unit = match.group(2).lower()
    delta_fn = _UNIT_TO_DELTA.get(unit)
    if delta_fn:
        return ref - delta_fn(amount)
    return ref


def _parse_csv_row(
    row: dict[str, str],
    *,
    reference: datetime,
) -> ParsedNewsRow | None:
    title = (row.get("Title") or row.get("title") or "").strip()
    if not title:
        return None

    tag = (row.get("Tag") or row.get("tag") or "").strip()
    content = (row.get("Content") or row.get("content") or "").strip()
    category = (row.get("Category") or row.get("category") or "").strip() or None

    body = f"{title} {content}".strip()
    sentiment_score, sentiment_label = score_sentiment_vader(body)
    tickers = extract_tickers_from_text(body)
    published_at = parse_relative_published_at(content or title, reference=reference)

    relevance = compute_market_relevance(body)
    if tickers:
        relevance = max(relevance, _compute_relevance(body, tickers[0]))
    elif tag.lower() in {"earnings", "stocks", "stock market"}:
        relevance = max(relevance, 0.35)

    extracted_events: list[dict[str, Any]] = []
    if tag or category:
        extracted_events.append(
            {
                "event_type": "macro" if not tickers else "other",
                "tag": tag or None,
                "category": category,
                "market_effect": sentiment_label,
                "confidence": round(abs(sentiment_score), 3),
            }
        )

    description_parts = [part for part in (tag, category) if part]
    description = " · ".join(description_parts) if description_parts else None

    return ParsedNewsRow(
        title=title[:1000],
        tag=tag,
        content=content[:8000] if content else "",
        category=category,
        published_at=published_at,
        sentiment_score=sentiment_score,
        sentiment_label=sentiment_label,
        tickers_mentioned=tickers,
        url=synthetic_url(title),
        description=description,
        extracted_events=extracted_events,
        relevance_score=round(relevance, 3),
    )


def iter_csv_rows(csv_path: Path, *, reference: datetime) -> Iterable[ParsedNewsRow]:
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            parsed = _parse_csv_row(raw, reference=reference)
            if parsed is not None:
                yield parsed


async def import_csv_news(
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
    if not may_store(CSV_SOURCE):
        logger.warning("csv_news_import_blocked_license", source=CSV_SOURCE)
        return stats
    root = prepare_data_directory(
        Path(data_dir) if data_dir is not None else default_news_csv_dir()
    )
    ref = reference or datetime.now(timezone.utc)
    seen_titles: set[str] = set()
    pending = 0

    for csv_path in discover_csv_files(root):
        stats.files_seen += 1
        for parsed in iter_csv_rows(csv_path, reference=ref):
            if parsed.title in seen_titles:
                stats.skipped_duplicate += 1
                continue
            seen_titles.add(parsed.title)
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
                    source=CSV_SOURCE,
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
                    logger.warning("CSV news batch commit failed", error=str(exc))
                pending = 0

        if limit is not None and stats.rows_parsed >= limit:
            break

    if not dry_run and pending:
        try:
            await db.commit()
        except Exception as exc:
            await db.rollback()
            stats.errors.append(str(exc))
            logger.warning("CSV news final commit failed", error=str(exc))

    logger.info(
        "CSV news import finished",
        files=stats.files_seen,
        parsed=stats.rows_parsed,
        inserted=stats.inserted,
        skipped=stats.skipped_duplicate,
        dry_run=dry_run,
    )
    return stats
