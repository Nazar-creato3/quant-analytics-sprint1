"""Founder metrics from product events. The SQL file is the only formula."""
from __future__ import annotations

import json
import sqlite3
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.services.product_analytics.service import stored_events
from app.services.qa.feature_flags import is_enabled

_MISSING = "нет данных"
_SQL = Path(__file__).with_name("metrics.sql")
_CONFIG = Path(__file__).with_name("config.json")
_FUNNEL = (
    "maneuver_proposed",
    "maneuver_viewed",
    "maneuver_edited",
    "maneuver_approved",
    "maneuver_rejected",
    "maneuver_executed",
)


def _queries() -> dict[str, str]:
    found: dict[str, str] = {}
    name = ""
    lines: list[str] = []
    for line in _SQL.read_text(encoding="utf-8").splitlines():
        if line.startswith("-- name:"):
            if name:
                found[name] = "\n".join(lines).strip()
            name = line.split(":", 1)[1].strip()
            lines = []
        else:
            lines.append(line)
    if name:
        found[name] = "\n".join(lines).strip()
    return found


def _ratio(part: int, whole: int) -> str:
    if whole == 0:
        return _MISSING
    return f"{part}/{whole}"


def _median(values: list[int]) -> str:
    if not values:
        return _MISSING
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return str(ordered[mid])
    left = Decimal(ordered[mid - 1])
    right = Decimal(ordered[mid])
    return str((left + right) / Decimal(2))


def _props(raw: Any) -> dict[str, str]:
    if isinstance(raw, dict):
        return {str(key): str(value) for key, value in raw.items()}
    if isinstance(raw, str) and raw:
        loaded = json.loads(raw)
        if isinstance(loaded, dict):
            return {str(key): str(value) for key, value in loaded.items()}
    return {}


def metrics_for(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not is_enabled("qa_founder_metrics"):
        return {"status": "off"}
    queries = _queries()
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute(
            "CREATE TABLE events ("
            "name TEXT, subject_pseudo TEXT, recorded_at TEXT, venue TEXT, reason TEXT, mode TEXT)"
        )
        for row in rows:
            props = _props(row.get("properties"))
            conn.execute(
                "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?)",
                (
                    row.get("name"),
                    row.get("subject_pseudo"),
                    row.get("recorded_at"),
                    props.get("venue", ""),
                    props.get("reason", ""),
                    props.get("mode", ""),
                ),
            )
        connects, activated = conn.execute(queries["activation"]).fetchone()
        cohorts = [
            {"cohort": cohort, "users": str(users), "returned": str(returned)}
            for cohort, users, returned in conn.execute(queries["retention"]).fetchall()
        ]
        hours = [int(value) for (value,) in conn.execute(queries["hours"]).fetchall()]
        registered, completed = conn.execute(queries["profile"]).fetchone()
        counts = {name: int(n) for name, n in conn.execute(queries["funnel"]).fetchall()}
        errors = {venue: str(n) for venue, n in conn.execute(queries["errors"]).fetchall()}
    finally:
        conn.close()
    funnel: Any = _MISSING
    if sum(counts.values()) > 0:
        funnel = {name: str(counts.get(name, 0)) for name in _FUNNEL}
    return {
        "status": "ok",
        "main_metric": "activation",
        "main_target": _MISSING,
        "activation": _ratio(int(activated), int(connects)),
        "retention": cohorts or _MISSING,
        "funnel": funnel,
        "profile_share": _ratio(int(completed), int(registered)),
        "time_to_report": _median(hours),
        "connect_errors": errors or _MISSING,
    }


def metrics() -> dict[str, Any]:
    return metrics_for(stored_events())


def export_lines(snapshot: dict[str, Any] | None = None) -> list[str]:
    current = snapshot if snapshot is not None else metrics()
    if current.get("status") == "off":
        return ["status off"]
    return [
        f"активация {current['activation']}",
        f"удержание {current['retention']}",
        f"воронка {current['funnel']}",
        f"анкеты {current['profile_share']}",
        f"время до отчёта {current['time_to_report']}",
        f"ошибки подключения {current['connect_errors']}",
    ]


def weekly_summary() -> dict[str, str]:
    if not is_enabled("qa_founder_metrics"):
        return {"status": "off", "text": "", "channel": "slack"}
    json.loads(_CONFIG.read_text(encoding="utf-8"))
    delivery = _MISSING
    text = "; ".join(export_lines()) + f"; slack {delivery}"
    return {"status": delivery, "text": text, "channel": "slack"}
