"""Checksum budget and an in-process 1000-session load. Not k6/Locust."""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.services.qa.feature_flags import is_enabled

MODEL_VERSION = "perf_budget.v1"
_MISSING = "нет данных"
_CONFIG = Path(__file__).with_name("config.json")
_last: dict[str, str] | None = None


def reset() -> None:
    global _last
    _last = None


def _cfg() -> dict[str, Any]:
    return json.loads(_CONFIG.read_text(encoding="utf-8"))


def _session(_n: int) -> int:
    """One cheap session: one position, one day."""
    return 1


def budget_run() -> dict[str, str]:
    """Sum one unit per position-day, then 1000 in-process sessions."""
    global _last
    if not is_enabled("qa_perf_budget"):
        return {"status": "off"}
    cfg = _cfg()
    positions = int(cfg["measured_positions"])
    days = int(cfg["measured_days"])
    users = int(cfg["target_users"])
    started = time.perf_counter()
    total = Decimal(0)
    unit = Decimal(1)
    for _ in range(positions):
        for _day in range(days):
            total += unit
    after_checksum_ms = Decimal(str((time.perf_counter() - started) * 1000))
    load_started = time.perf_counter()
    workers = int(cfg.get("load_workers") or 32)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        sessions = list(pool.map(_session, range(users)))
    load_ms = Decimal(str((time.perf_counter() - load_started) * 1000))
    elapsed_ms = Decimal(str((time.perf_counter() - started) * 1000))
    row = {
        "status": "measured",
        "model_version": MODEL_VERSION,
        "positions": str(positions),
        "days": str(days),
        "checksum": format(total, "f"),
        "elapsed_ms": format(elapsed_ms, "f"),
        "checksum_ms": format(after_checksum_ms, "f"),
        "load_ms": format(load_ms, "f"),
        "ceiling_ms": str(cfg["ceiling_ms"]),
        "target_users": str(users),
        "target_positions": str(cfg["target_positions"]),
        "target_history_days": str(cfg["target_history_days"]),
        "users_executed": str(len(sessions)),
        "load_workers": str(workers),
        "database_profile": _MISSING,
        "worker_limits": _MISSING,
    }
    _last = row
    return dict(row)


def last_budget() -> dict[str, str]:
    if _last is None:
        return {"status": _MISSING, "users_executed": _MISSING, "database_profile": _MISSING}
    return dict(_last)
