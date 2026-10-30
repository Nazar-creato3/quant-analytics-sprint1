"""News ingest pipeline: license → normalize → near-dup → entity → event → sentiment."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from app.services.news.entity_relevance import _TICKER_ALIASES, entity_relevance_score
from app.services.news.license import may_show, may_store, tag_for_news_source
from app.services.pit.news_events import classify_event

_RU_EVENTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("dividend", ("дивиденд", "dividend")),
    ("cbr", ("банк россии", "цб рф", "ключев", "cbr ")),
    ("sanctions", ("санкц", "sanction")),
    ("earnings", ("отчётн", "отчетн", "мсфо", "финрезультат")),
    ("m_and_a", ("слияние", "поглощение", "merger", "acquisition")),
    ("guidance", ("прогноз", "guidance", "outlook")),
)

_POS = ("рост", "прибыл", "beat", "raises", "объявил дивиденд", "recommended")
_NEG = ("санкц", "убыт", "miss", "cuts", "отменил дивиденд", "повысил ставку")


def normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", (title or "").strip().lower())


def _shingles(text: str, k: int = 3) -> set[str]:
    tokens = normalize_title(text).split()
    if len(tokens) < k:
        return {" ".join(tokens)} if tokens else set()
    return {" ".join(tokens[i : i + k]) for i in range(len(tokens) - k + 1)}


def is_near_duplicate(a: str, b: str, *, threshold: float = 0.55) -> bool:
    sa, sb = _shingles(a), _shingles(b)
    if not sa or not sb:
        return False
    j = len(sa & sb) / len(sa | sb)
    return j >= threshold


def classify_news_event(title: str) -> str:
    low = title.lower()
    for label, needles in _RU_EVENTS:
        if any(n in low for n in needles):
            return label
    return classify_event(title)


def link_tickers(title: str) -> list[str]:
    hits: list[str] = []
    for ticker, aliases in _TICKER_ALIASES.items():
        if entity_relevance_score(title, ticker).score >= 0.3:
            hits.append(ticker)
            continue
        blob = title.lower()
        if ticker.lower() in blob or any(a in blob for a in aliases):
            hits.append(ticker)
    return hits


def sentiment_lexicon(title: str) -> str:
    low = title.lower()
    pos = sum(1 for w in _POS if w in low)
    neg = sum(1 for w in _NEG if w in low)
    if pos > neg:
        return "positive"
    if neg > pos:
        return "negative"
    return "neutral"


def latency_seconds(*, published_at: datetime, shown_at: datetime) -> float:
    return max(0.0, (shown_at - published_at).total_seconds())


def process_article(
    raw: dict[str, Any],
    *,
    audience: str = "internal",
    now: datetime | None = None,
    seen_titles: list[str] | None = None,
) -> dict[str, Any] | None:
    source = str(raw.get("source") or "")
    if not may_store(source):
        return None
    title = str(raw.get("title") or "")
    if seen_titles and any(is_near_duplicate(title, prev) for prev in seen_titles):
        return None
    published = raw.get("published_at")
    shown = now or datetime.now(timezone.utc)
    if isinstance(published, str):
        published = datetime.fromisoformat(published.replace("Z", "+00:00"))
    if not isinstance(published, datetime):
        published = shown
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    tickers = link_tickers(title)
    event = classify_news_event(title)
    tag = tag_for_news_source(source)
    visible = may_show(source, audience=audience)  # type: ignore[arg-type]
    body_hash = hashlib.sha256(normalize_title(title).encode()).hexdigest()[:16]
    return {
        "title": title if visible else None,
        "title_hash": body_hash,
        "source": source,
        "license_tag": tag,
        "display_allowed": visible,
        "tickers": tickers,
        "event": event,
        "sentiment": sentiment_lexicon(title),
        "published_at": published.isoformat(),
        "latency_sec": latency_seconds(published_at=published, shown_at=shown),
        "knowledge_time": published.isoformat(),
    }


def ingest_batch(rows: list[dict[str, Any]], *, audience: str = "internal") -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: list[str] = []
    now = datetime.now(timezone.utc)
    for row in rows:
        item = process_article(row, audience=audience, now=now, seen_titles=seen)
        if item is None:
            continue
        raw_title = str(row.get("title") or "")
        seen.append(raw_title)
        out.append(item)
    return out
