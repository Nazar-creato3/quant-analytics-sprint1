"""Research → production: human confirm + sign-off log. Reuses alpha model_card + MFA if sent."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from app.core.config import settings
from app.services.alpha.model_card import ModelCard, human_promote, list_research_cards


def _log_path() -> Path:
    raw = getattr(settings, "PLATFORM_PROMOTE_DIR", "") or ""
    root = Path(raw) if str(raw).strip() else Path("/app/data/platform")
    return root / "promote_signoff.jsonl"


def append_signoff(row: Mapping[str, Any]) -> dict[str, Any]:
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        **dict(row),
    }
    path = _log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
        payload["persisted"] = True
    except OSError:
        payload["persisted"] = False
    return payload


def list_signoffs(*, limit: int = 20) -> list[dict[str, Any]]:
    path = _log_path()
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for line in lines[-max(1, limit) :]:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return list(reversed(out))


def promote_with_signoff(
    card: ModelCard,
    *,
    confirm: bool,
    reviewer: str,
    totp_ok: bool | None = None,
    note: str = "",
) -> dict[str, Any]:
    """MFA already exists on the user; totp_ok=False refuses. None = not required (tests/paper)."""
    if totp_ok is False:
        raise ValueError("MFA sign-off required (TOTP)")
    result = human_promote(card, confirm=confirm, reviewer=reviewer)
    append_signoff(
        {
            "reviewer": reviewer,
            "name": card.name,
            "version": card.version,
            "feature_freeze_id": card.feature_freeze_id,
            "mfa": totp_ok is True,
            "note": note,
        }
    )
    result["signoff"] = {"reviewer": reviewer, "mfa": totp_ok is True}
    return result


def research_queue(*, reviewer: str | None = None) -> dict[str, Any]:
    cards = list_research_cards()
    live = next((c for c in cards if c.get("promoted") or c.get("is_live")), None)
    signoffs = list_signoffs(limit=50)
    if reviewer:
        want = str(reviewer).strip().lower()
        signoffs = [s for s in signoffs if str(s.get("reviewer") or "").strip().lower() == want][:10]
    else:
        signoffs = signoffs[:10]
    return {
        "cards": cards,
        "live": live,
        "signoffs": signoffs,
        "gate_ru": "Выпуск модели — только после ручного подтверждения. MFA если включён у оператора.",
    }
