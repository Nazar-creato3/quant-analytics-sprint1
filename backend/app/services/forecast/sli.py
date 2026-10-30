"""Forecast SLI from last-good sidecars. No Loki — local files only."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import settings


def model_sli(model_dir: Path | None = None) -> dict[str, Any]:
    from app.services.ml.model import MODEL_DIR

    folder = model_dir or MODEL_DIR
    sidecars = sorted(folder.glob("*.cv.json")) if folder.is_dir() else []
    now = datetime.now(timezone.utc)
    ages_h: list[float] = []
    cvs: list[float] = []
    stale = 0
    for path in sidecars[:80]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            cv = float(payload.get("cv") or 0.0)
            cvs.append(cv)
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            age_h = (now - mtime).total_seconds() / 3600.0
            ages_h.append(age_h)
            if age_h > 48:
                stale += 1
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
    ece = None
    try:
        from app.services.forecast.calibration import load_ece

        ece = load_ece()
    except Exception:
        ece = None
    return {
        "sidecar_count": len(sidecars),
        "stale_over_48h": stale,
        "median_purged_cv": round(float(sorted(cvs)[len(cvs) // 2]), 4) if cvs else None,
        "oldest_hours": round(max(ages_h), 1) if ages_h else None,
        "tier_c_live_fetch": bool(getattr(settings, "TIER_C_LIVE_FETCH", False)),
        "ece": ece,
        "note_ru": "SLI с диска моделей. Ярус C не дергается. Loki не подключён.",
    }
