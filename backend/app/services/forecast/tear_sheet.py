"""Daily paper tear-sheet: ECE, DSR, turnover. Files only."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from app.core.config import settings


def _dir() -> Path:
    raw = getattr(settings, "DAILY_BOOK_DIR", "") or ""
    return Path(raw) if raw.strip() else Path("/app/data/daily_books")


def load_previous_book(current_as_of: str | None) -> dict[str, Any] | None:
    folder = _dir()
    files = [p for p in sorted(folder.glob("????-??-??.json")) if ".realized" not in p.name]
    if current_as_of:
        files = [p for p in files if p.stem < str(current_as_of)]
    if not files:
        return None
    try:
        return json.loads(files[-1].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def load_latest_tear_sheet() -> dict[str, Any] | None:
    folder = _dir()
    files = sorted(folder.glob("????-??-??.tearsheet.json"))
    if not files:
        return None
    try:
        return json.loads(files[-1].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def book_turnover(prev: Mapping[str, Any] | None, cur: Mapping[str, Any] | None) -> float | None:
    """One-way turnover: 0.5 * L1 weight change. None if a book is missing."""
    if not prev or not cur:
        return None
    a = {str(h.get("symbol")).upper(): float(h.get("weight") or 0) for h in (prev.get("holdings") or [])}
    b = {str(h.get("symbol")).upper(): float(h.get("weight") or 0) for h in (cur.get("holdings") or [])}
    names = set(a) | set(b)
    if not names:
        return 0.0
    return round(0.5 * sum(abs(a.get(n, 0.0) - b.get(n, 0.0)) for n in names), 6)


def write_tear_sheet(payload: Mapping[str, Any]) -> Path | None:
    folder = _dir()
    day = str(payload.get("as_of") or datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    try:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{day}.tearsheet.json"
        path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2), encoding="utf-8")
        return path
    except OSError:
        return None
