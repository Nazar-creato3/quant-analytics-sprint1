"""Collect, rank, journal. Production order uses weight 1 unless founder review is on."""

from __future__ import annotations

from datetime import date
from typing import Any

from app.services.decision_core.calibrate import live_weights, shadow_block
from app.services.decision_core.journal import record_shown
from app.services.decision_core.map import MAPPERS, texts
from app.services.decision_core.sources import Source, default_sources, gather
from app.services.qa.feature_flags import is_enabled

SCREEN_MIN = 3
SCREEN_MAX = 5


def _rank(signals: list[dict[str, Any]], weights: dict[str, float]) -> list[dict[str, Any]]:
    def score(row: dict[str, Any]) -> float:
        factor = 1.0 if row["data_status"] == "ok" else 0.6
        weight = weights.get(row["signal_id"], 1.0)
        return float(row["importance"]) * factor * weight

    ordered = sorted(signals, key=lambda row: (score(row), row["signal_id"]), reverse=True)
    for index, row in enumerate(ordered, start=1):
        row["rank"] = index
        row["weight"] = weights.get(row["signal_id"], 1.0)
    return ordered


def collect_signals(
    *,
    user_id: str,
    mode: str = "paper",
    portfolio_id: str | None = None,
    extra: dict[str, Any] | None = None,
    sources: dict[str, Source] | None = None,
    as_of: date | None = None,
    record: bool = True,
    timeout_s: float = 8.0,
) -> dict[str, Any]:
    bundle = texts()
    if not is_enabled("qa_decision_core", user_id=user_id):
        return {
            "data_status": "нет данных",
            "reason": "qa_decision_core off",
            "caption": bundle.get("flag_off") or "нет данных",
            "signals": [],
            "screen": [],
            "missing": [],
            "journal": [],
            "shadow_weights": None,
        }
    book = portfolio_id or user_id
    payloads, missing = gather(
        user_id, mode, book, extra or {}, sources or default_sources(), timeout_s=timeout_s
    )
    signals: list[dict[str, Any]] = []
    for key, payload in payloads.items():
        mapper = MAPPERS.get(key)
        if mapper is None:
            continue
        signal = mapper(payload)
        if signal is None:
            reason = str(payload.get("reason") or payload.get("data_status") or "нет данных")
            missing.append({"module": key, "reason": reason})
            continue
        signals.append(signal)
    weights = live_weights(user_id)
    ordered = _rank(signals, weights)
    screen = ordered[:SCREEN_MAX]
    journal = record_shown(user_id, screen, as_of=as_of) if record and screen else []
    status = "ok" if len(screen) >= SCREEN_MIN else ("частично" if screen else "нет данных")
    return {
        "data_status": status,
        "reason": None if status == "ok" else bundle.get("empty"),
        "caption": bundle.get("caption"),
        "methodology": "/methodology/decision-core",
        "signals": ordered,
        "screen": screen,
        "missing": missing,
        "journal": journal,
        "shadow_weights": shadow_block(user_id),
        "weights_live": bool(weights),
    }
