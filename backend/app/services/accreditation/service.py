"""Version ledger and journal replay for the accreditation pack.

A sealed journal event keeps the algorithm version that was written.
Changing that field breaks the hash. A logic change needs a new row in
registry.json; this module does not turn on live advice.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_REGISTRY = Path(__file__).with_name("registry.json")
_MISSING = "нет данных"


def code_versions() -> dict[str, str]:
    """Versions of the modules that form a maneuver, read from their owners."""
    from app.services.act_desk.service import MODEL_VERSION as act_desk
    from app.services.investment_profile.service import MODEL_VERSION as profile
    from app.services.maneuver_control.service import MODEL_VERSION as control
    from app.services.maneuver_history.simulate import MODEL_VERSION as history
    from app.services.maneuvers.service import MODEL_VERSION as maneuvers
    from app.services.risk_engine.fhs import CONFIG_VERSION as risk
    from app.services.stress_library.service import CONFIG_VERSION as stress
    from app.services.target_portfolio.types import MODEL_VERSION as target

    return {
        "act_desk": act_desk,
        "investment_profile": profile,
        "maneuver_control": control,
        "maneuver_history": history,
        "maneuvers": maneuvers,
        "risk": risk,
        "stress": stress,
        "target_portfolio": target,
    }


def registry_records() -> list[dict[str, Any]]:
    """Append-only version records. The file is the ledger."""
    raw = json.loads(_REGISTRY.read_text(encoding="utf-8"))
    records = raw.get("records")
    if not isinstance(records, list) or not records:
        return []
    return records


def versions_match(code: dict[str, str] | None = None) -> bool:
    """True when `code` equals the latest ledger row. A new version must be appended."""
    records = registry_records()
    if not records:
        return False
    latest = records[-1].get("versions")
    if not isinstance(latest, dict):
        return False
    current = code if code is not None else code_versions()
    return current == latest


def replay_from_journal(event: dict[str, Any]) -> dict[str, Any]:
    """Read the stored maneuver. Does not recompute prices or orders."""
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    maneuver = payload.get("maneuver") if isinstance(payload.get("maneuver"), dict) else {}
    orders = maneuver.get("orders")
    if orders is None:
        orders = payload.get("orders")
    rationale = maneuver.get("rationale") or payload.get("rationale") or _MISSING
    return {
        "model_version": event.get("model_version") or _MISSING,
        "model_versions": event.get("model_versions") if isinstance(event.get("model_versions"), dict) else {},
        "shown_text": event.get("shown_text") or _MISSING,
        "profile_snapshot": event.get("profile_snapshot") if isinstance(event.get("profile_snapshot"), dict) else {},
        "kind": maneuver.get("kind") or _MISSING,
        "orders": orders if orders is not None else _MISSING,
        "rationale": rationale,
        "hash": event.get("hash") or _MISSING,
    }
