"""Every size decision: deploy_cap, weights, veto. JSONL, no secrets."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.core.config import settings


def _dir() -> Path:
    raw = getattr(settings, "OPS_AUDIT_DIR", "") or ""
    return Path(raw) if str(raw).strip() else Path("/app/data/ops_audit")


def record(
    *,
    deploy_cap: float,
    weights: Mapping[str, float] | Sequence[tuple[str, float]],
    veto: Sequence[str] = (),
    user_id: str = "paper",
    account: str = "paper",
    sleeve: str = "retail_long_only",
    extra: Mapping[str, Any] | None = None,
    dest: Path | None = None,
) -> dict[str, Any]:
    if isinstance(weights, Mapping):
        w = {str(k).upper(): float(v) for k, v in weights.items()}
    else:
        w = {str(k).upper(): float(v) for k, v in weights}
    row = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "user_id": str(user_id),
        "account": str(account),
        "sleeve": str(sleeve),
        "deploy_cap": float(deploy_cap),
        "weights": w,
        "veto": [str(x) for x in veto],
    }
    if extra:
        row["extra"] = dict(extra)
    path = dest or (_dir() / "size_decisions.jsonl")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        row["persisted"] = False
    return row
