"""DR: deploy-floor seal + last-good copy of digests/features. No cloud backup vendor."""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.risk.portfolio_sizing import resolve_deploy_cap_for_sizing


def _dr_root() -> Path:
    raw = getattr(settings, "OPS_DR_DIR", "") or ""
    return Path(raw) if str(raw).strip() else Path("/app/data/ops_dr")


def seal_deploy_floor(
    settings_cap: float | None,
    account_total: float | None = None,
    *,
    dest: Path | None = None,
) -> dict[str, Any]:
    """Persist the operator floor. Readers must not replace it with $10k."""
    cap = resolve_deploy_cap_for_sizing(settings_cap, account_total)
    payload = {
        "sealed_at": datetime.now(timezone.utc).isoformat(),
        "settings_cap": float(settings_cap or 0.0),
        "account_total": float(account_total or 0.0),
        "deploy_cap": cap,
        "rule": "never_replace_operator_cap_with_10k",
    }
    path = dest or (_dr_root() / "deploy_floor.json")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        payload["persisted"] = False
    return payload


def read_floor(dest: Path | None = None) -> float | None:
    path = dest or (_dr_root() / "deploy_floor.json")
    if not path.is_file():
        return None
    try:
        return float(json.loads(path.read_text(encoding="utf-8")).get("deploy_cap") or 0.0) or None
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def backup_last_good(
    sources: list[Path],
    *,
    dest_root: Path | None = None,
) -> dict[str, Any]:
    """Copy existing digest/feature files to last-good. Skip missing. Never overwrite a better stamp blindly."""
    root = dest_root or (_dr_root() / "last_good")
    root.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    skipped: list[str] = []
    for src in sources:
        if not src.exists():
            skipped.append(str(src))
            continue
        target = root / src.name
        if src.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(src, target)
        else:
            shutil.copy2(src, target)
        copied.append(str(src.name))
    stamp = root / "MANIFEST.json"
    payload = {
        "backed_up_at": datetime.now(timezone.utc).isoformat(),
        "copied": copied,
        "skipped": skipped,
    }
    stamp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload
