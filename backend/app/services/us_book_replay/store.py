"""Read replay frames built by ``itch.build`` and pick the frame for "now".

Layout under ``US_BOOK_DIR`` (default ``/app/data/us_book``)::

    <session>/meta.json
    <session>/<SYMBOL>.jsonl.gz

The panel polls once a second; we map the current New York time of day onto
the recorded session (during US trading hours the same clock time, otherwise a
loop through the session), so the book moves exactly as it moved that day.
"""
from __future__ import annotations

import bisect
import gzip
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.services.us_book_replay.itch import SESSION_CLOSE, SESSION_OPEN

NY = ZoneInfo("America/New_York")
_cache: dict[str, tuple[float, list[int], list[str]]] = {}


def root() -> Path:
    env = os.environ.get("US_BOOK_DIR", "").strip()
    # No repo-checkout fallback: a stray local replay must never leak into tests or dev.
    for cand in ([Path(env)] if env else []) + [Path("/app/data/us_book")]:
        if cand.is_dir():
            return cand
    return Path(env) if env else Path("/app/data/us_book")


def latest_session() -> tuple[Path, dict[str, Any]] | None:
    base = root()
    if not base.is_dir():
        return None
    sessions = sorted((p for p in base.iterdir() if (p / "meta.json").is_file()), key=lambda p: p.name)
    if not sessions:
        return None
    path = sessions[-1]
    try:
        return path, json.loads((path / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def available(symbol: str) -> bool:
    hit = latest_session()
    return bool(hit and symbol.upper() in (hit[1].get("symbols") or {}))


def _frames(path: Path) -> tuple[list[int], list[str]]:
    key = str(path)
    mtime = path.stat().st_mtime
    hit = _cache.get(key)
    if hit and hit[0] == mtime:
        return hit[1], hit[2]
    times: list[int] = []
    lines: list[str] = []
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            # "t" is the first key: cheap parse without loading the whole frame
            t = int(line[5 : line.index(",")])
            times.append(t)
            lines.append(line)
    _cache[key] = (mtime, times, lines)
    return times, lines


def replay_clock(now: datetime | None = None) -> int:
    """Seconds since midnight to show: same NY clock time during the session, else a loop."""
    ny = (now or datetime.now(timezone.utc)).astimezone(NY)
    sec = ny.hour * 3600 + ny.minute * 60 + ny.second
    if ny.weekday() < 5 and SESSION_OPEN <= sec < SESSION_CLOSE:
        return sec
    span = SESSION_CLOSE - SESSION_OPEN
    return SESSION_OPEN + int(time.time()) % span


def frame(symbol: str, at: int | None = None) -> dict[str, Any] | None:
    hit = latest_session()
    if not hit:
        return None
    path, meta = hit
    f = path / f"{symbol.upper()}.jsonl.gz"
    if not f.is_file():
        return None
    times, lines = _frames(f)
    if not times:
        return None
    t = replay_clock() if at is None else int(at)
    i = max(0, bisect.bisect_right(times, t) - 1)
    out = json.loads(lines[i])
    out["session"] = meta.get("session")
    out["step"] = meta.get("step")
    return out


def clock_text(sec: int) -> str:
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"
