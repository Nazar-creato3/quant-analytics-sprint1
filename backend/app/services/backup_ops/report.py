"""Weekly restore-check report (founder: RPO 24h, RTO 4h)."""
from __future__ import annotations

import json
from pathlib import Path

_PATH = Path(__file__).resolve().parents[4] / "docs" / "ops" / "backup-restore-check.json"
RPO_HOURS = 24
RTO_HOURS = 4


def load_report() -> dict:
    if not _PATH.exists():
        return {
            "rpo_hours": RPO_HOURS,
            "rto_hours": RTO_HOURS,
            "last_check": None,
            "status": "нет данных",
            "note": "weekly restore check not recorded yet",
        }
    data = json.loads(_PATH.read_text(encoding="utf-8"))
    data.setdefault("rpo_hours", RPO_HOURS)
    data.setdefault("rto_hours", RTO_HOURS)
    return data


def lines() -> list[str]:
    r = load_report()
    return [
        "Backup restore check",
        f"RPO {r['rpo_hours']}h / RTO {r['rto_hours']}h",
        f"Last check: {r.get('last_check') or 'нет данных'}",
        f"Status: {r.get('status') or 'нет данных'}",
    ]
