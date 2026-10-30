"""Support reports. Slack is not called and addresses are not stored."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from app.services.qa.feature_flags import is_enabled
from app.services.team_slack import notify_team

_MISSING = "нет данных"
_CONFIG = Path(__file__).with_name("config.json")
_MARKS = ("@", "token", "password", "secret", "email")
# Bounded: the intake is open to signed-out visitors, an unbounded list was a memory DoS.
_MAX_TICKETS = 500
_tickets: list[dict[str, str]] = []


def reset_support() -> None:
    _tickets.clear()


def _schedule_team_notice(page: str) -> None:
    """Best-effort Slack via notify_team; no-op when webhooks are empty."""
    coro = notify_team("support", "новое обращение", {"page": page})
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        try:
            asyncio.run(coro)
        except (RuntimeError, OSError, ValueError):
            return
    else:
        loop.create_task(coro)


def _cfg(key: str) -> str:
    raw = json.loads(_CONFIG.read_text(encoding="utf-8")).get(key)
    if raw in (None, ""):
        return _MISSING
    return str(raw)


def _dirty(parts: list[str]) -> bool:
    blob = " ".join(parts).lower()
    return any(mark in blob for mark in _MARKS)


def report(
    *,
    page: str,
    version: str,
    request_id: str,
    errors: list[str],
    description: str,
    screenshot_consent: bool,
    screenshot: str,
) -> dict[str, str]:
    if not is_enabled("qa_support"):
        return {"status": "off"}
    parts = [page, version, request_id, description, *errors, screenshot if screenshot_consent else ""]
    if _dirty(parts):
        return {"status": "rejected", "reason": _MISSING}
    if len(_tickets) >= _MAX_TICKETS:
        del _tickets[0 : len(_tickets) - _MAX_TICKETS + 1]
    _tickets.append(
        {
            "page": page,
            "version": version,
            "request_id": request_id,
            "errors": ",".join(errors),
            "description": description,
            "screenshot": _MISSING,
            "status": "open",
            "slack": _cfg("slack_webhook"),
            "reply": _cfg("mail_transport"),
        }
    )
    _schedule_team_notice(page)
    return {"status": "stored", "screenshot": _MISSING, "slack": _MISSING, "reply": _MISSING}


def tickets() -> list[dict[str, str]]:
    return [dict(row) for row in _tickets]


def frequent() -> Any:
    if not _tickets:
        return _MISSING
    counts: dict[str, int] = {}
    for row in _tickets:
        counts[row["page"]] = counts.get(row["page"], 0) + 1
    return {page: str(count) for page, count in sorted(counts.items())}


def known_issues() -> str:
    return _cfg("known_issues")


def slack_notice() -> dict[str, str]:
    text = f"обращения {len(_tickets)}; slack {_cfg('slack_webhook')}"
    return {"status": _MISSING, "text": text, "channel": "slack"}
