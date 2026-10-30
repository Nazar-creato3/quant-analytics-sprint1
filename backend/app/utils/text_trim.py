"""Display-safe text trimming — no mid-word cuts or dangling label fragments."""
from __future__ import annotations

import re

_INCOMPLETE_LABEL_TAIL = re.compile(
    r"\s+(?:MACD|RSI|Объём|R:R|Режим|Новостной фон)\s*:\s*$",
    re.IGNORECASE,
)


def strip_incomplete_tail(text: str) -> str:
    """Remove trailing incomplete clauses like ``MACD:`` or partial label words."""
    cleaned = (text or "").strip()
    if not cleaned:
        return ""
    prev = None
    while prev != cleaned:
        prev = cleaned
        cleaned = _INCOMPLETE_LABEL_TAIL.sub("", cleaned).rstrip(".,;: ")
    return cleaned


def trim_display_text(text: str, max_len: int) -> str:
    """Trim ``text`` to ``max_len`` at a word/sentence boundary; strip incomplete tails."""
    cleaned = (text or "").strip()
    if not cleaned:
        return ""
    if len(cleaned) <= max_len:
        return strip_incomplete_tail(cleaned)

    chunk = cleaned[:max_len]
    for sep in (". ", "; ", ", ", " "):
        idx = chunk.rfind(sep)
        if idx > max_len * 0.45:
            chunk = chunk[: idx + (1 if sep.strip() == "." else 0)]
            break
    else:
        chunk = chunk.rstrip()

    # If we still cut mid-word (e.g. «Новостно»), drop the trailing fragment.
    if chunk and chunk[-1].isalnum() and len(cleaned) > len(chunk):
        space_idx = chunk.rfind(" ")
        if space_idx > 0:
            chunk = chunk[:space_idx]

    result = strip_incomplete_tail(chunk.rstrip(".,;: "))
    return f"{result}…" if result else "…"
