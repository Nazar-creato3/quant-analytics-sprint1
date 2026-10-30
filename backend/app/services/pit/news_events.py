"""Free RSS + FinBERT polarity, plus event taxonomy (not polarity-only)."""
from __future__ import annotations

import re
from typing import Any

from app.services.pit.clock import as_day, infer_knowledge_time

_EVENT_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "earnings",
        (
            "earnings",
            "eps",
            "beats estimates",
            "misses estimates",
            "quarterly results",
            "q1 ",
            "q2 ",
            "q3 ",
            "q4 ",
        ),
    ),
    (
        "guidance",
        ("guidance", "outlook", "raises forecast", "cuts forecast", "full-year view"),
    ),
    (
        "m_and_a",
        ("acquire", "acquisition", "merger", "takeover", "buyout", "to buy"),
    ),
    (
        "litigation",
        ("lawsuit", "sued", "litigation", "settlement", "doj", "sec charges", "class action"),
    ),
)


def classify_all(title: str, body: str = "") -> list[str]:
    text = f"{title} {body}".lower()
    hits = [label for label, needles in _EVENT_PATTERNS if any(n in text for n in needles)]
    return hits or ["other"]


def classify_event(title: str, body: str = "") -> str:
    return classify_all(title, body)[0]


def article_observation(
    *,
    title: str,
    body: str = "",
    published_at: Any,
    polarity: float | None = None,
    engine: str = "unknown",
) -> dict[str, Any]:
    """knowledge_time = published_at (RSS arrival). Never the event the article describes."""
    published = as_day(published_at)
    known = infer_knowledge_time(published, series_id="NEWS", released=published)
    tags = classify_all(title, body)
    return {
        "event_time": published,
        "knowledge_time": known,
        "taxonomy": tags[0],
        "tags": tags,
        "polarity": None if polarity is None else max(-1.0, min(1.0, float(polarity))),
        "engine": engine,
        "title": title[:240],
    }


def taxonomy_features(articles: list[dict[str, Any]], *, as_of: Any) -> dict[str, float]:
    """Counts known by as_of. Look-ahead articles are dropped."""
    from app.services.pit.clock import as_day as _day

    cap = _day(as_of)
    counts = {"earnings": 0.0, "guidance": 0.0, "m_and_a": 0.0, "litigation": 0.0, "other": 0.0}
    pol = 0.0
    n = 0
    for art in articles:
        known = _day(art.get("knowledge_time") or art.get("published_at"))
        if not known or not cap or known > cap:
            continue
        tags = [str(t) for t in (art.get("tags") or [art.get("taxonomy") or "other"])]
        for key in tags:
            if key not in counts:
                key = "other"
            counts[key] += 1.0
        if art.get("polarity") is not None:
            pol += float(art["polarity"])
            n += 1
    counts["polarity_mean"] = (pol / n) if n else 0.0
    counts["n"] = float(sum(counts[k] for k in ("earnings", "guidance", "m_and_a", "litigation", "other")))
    return counts
