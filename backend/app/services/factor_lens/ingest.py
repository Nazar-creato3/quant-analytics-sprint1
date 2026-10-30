"""Daily factor return rebuild. Live ISS/CBR is optional; empty stays «нет данных»."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.services.factor_lens.names import FACTOR_ORDER
from app.services.factor_lens.orthogonalize import sequential_orthogonalize
from app.services.factor_lens.store import put_factor_panel

logger = get_logger(__name__)
FIXTURE = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "65" / "factor_panel.json"


def _synthetic_panel(*, n: int = 80, seed: int = 65) -> dict[str, Any]:
    import numpy as np

    rng = np.random.default_rng(seed)
    factors = {name: rng.normal(0.0, 0.01, n).tolist() for name in FACTOR_ORDER}
    start = date(2013, 1, 4)
    dates = []
    day = start
    while len(dates) < n:
        if day.weekday() < 5:
            dates.append(day.isoformat())
        day = date.fromordinal(day.toordinal() + 1)
    return {"source": "synthetic:65", "dates": dates, "factors": factors}


def load_fixture_panel(path: Path | None = None) -> dict[str, Any]:
    target = path or FIXTURE
    if target.is_file():
        return json.loads(target.read_text(encoding="utf-8"))
    return _synthetic_panel()


def rebuild_from_fixture(*, path: Path | None = None) -> dict[str, Any]:
    payload = load_fixture_panel(path)
    raw = payload.get("factors") or {}
    missing = [n for n in FACTOR_ORDER if n not in raw]
    dates = [date.fromisoformat(d) for d in payload.get("dates") or []]
    ortho = sequential_orthogonalize(raw)
    put_factor_panel(
        ortho,
        dates=dates[-len(next(iter(ortho.values()))) :] if ortho and dates else dates,
        source=str(payload.get("source") or "fixture:65"),
        missing=missing,
    )
    return {"n": {k: len(v) for k, v in ortho.items()}, "missing": missing, "source": "fixture:65"}


def rebuild_daily() -> dict[str, Any]:
    """Celery entry. Live ISS ingest is not invented; fixture/cache only."""
    try:
        return rebuild_from_fixture()
    except Exception as exc:
        logger.warning("factor_lens rebuild failed", error=str(exc)[:200])
        return {"n": {}, "missing": list(FACTOR_ORDER), "source": None, "error": "нет данных"}
