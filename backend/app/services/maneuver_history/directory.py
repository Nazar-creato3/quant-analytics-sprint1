"""Instrument directory that keeps names after they stop trading.

A missing delisting list is «нет данных» for that name. The name stays.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from app.services.maneuver_history.paths import delist_path

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DirectoryName:
    ticker: str
    delisted_on: date | None
    delist_note: str


def load_delist_notes(tickers: list[str], *, path: Path | None = None) -> dict[str, str]:
    """Per-name delist note. Absent file or absent ticker → «нет данных»."""
    file = delist_path() if path is None else path
    if not file.is_file():
        return {ticker: "нет данных" for ticker in tickers}
    raw = json.loads(file.read_text(encoding="utf-8"))
    listed = raw.get("delisted_on") if isinstance(raw, dict) else None
    if not isinstance(listed, dict):
        return {ticker: "нет данных" for ticker in tickers}
    notes: dict[str, str] = {}
    for ticker in tickers:
        value = listed.get(ticker)
        notes[ticker] = "нет данных" if value in (None, "") else str(value)
    return notes


def directory_from_notes(notes: dict[str, str]) -> list[DirectoryName]:
    names: list[DirectoryName] = []
    for ticker in sorted(notes):
        raw = notes[ticker]
        delisted: date | None = None
        if raw != "нет данных":
            try:
                delisted = date.fromisoformat(raw[:10])
            except ValueError:
                delisted = None
                raw = "нет данных"
        names.append(DirectoryName(ticker, delisted, raw))
    return names


def retain_names(names: list[DirectoryName], *, as_of: date) -> list[DirectoryName]:
    """Every name stays on `as_of`, including names that already stopped trading.

    A note of «нет данных» is not a reason to drop the row.
    """
    logger.debug("directory as_of=%s names=%s", as_of.isoformat(), len(names))
    kept: list[DirectoryName] = []
    for name in names:
        note = name.delist_note or "нет данных"
        if name.delisted_on is None:
            note = "нет данных"
        kept.append(DirectoryName(name.ticker, name.delisted_on, note))
    return kept


def is_tradable(name: DirectoryName, as_of: date) -> bool:
    """Unknown delist date stays tradable. A known end date on or before as_of does not."""
    if name.delisted_on is not None and name.delisted_on <= as_of:
        return False
    return True
