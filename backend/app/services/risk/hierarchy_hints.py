"""Cheap hints from already-cached PredictionHierarchy payloads (no live orchestrator)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class HierarchyHint:
    ticker: str
    recommendation: str = ""
    expected_sign: int = 0
    calibrated_confidence: float | None = None
    hmm_or_global_regime: str | None = None
    sector_momentum: float | None = None
    cache_hit: bool = False

    @property
    def is_avoid(self) -> bool:
        return self.recommendation == "avoid"

    @property
    def is_wait(self) -> bool:
        return self.recommendation == "wait"

    @property
    def avoid(self) -> bool:
        """Hard skip only for AVOID. WAIT is not a ban."""
        return self.is_avoid

    @property
    def preferred_direction(self) -> str | None:
        if self.expected_sign > 0:
            return "long"
        if self.expected_sign < 0:
            return "short"
        return None


def _payload_is_useful(cached: dict[str, Any]) -> bool:
    point = cached.get("point_forecast") if isinstance(cached.get("point_forecast"), dict) else {}
    action = cached.get("action_forecast") if isinstance(cached.get("action_forecast"), dict) else {}
    rec = str(action.get("recommendation") or "").strip()
    sign = point.get("expected_return_sign")
    cal = cached.get("calibrated_confidence")
    return bool(rec or sign in (-1, 1, "-1", "1") or cal is not None)


def hint_from_cached_forecast(ticker: str, cached: dict[str, Any] | None) -> HierarchyHint:
    sym = ticker.strip().upper()
    if not isinstance(cached, dict) or not _payload_is_useful(cached):
        return HierarchyHint(ticker=sym)
    point = cached.get("point_forecast") if isinstance(cached.get("point_forecast"), dict) else {}
    action = cached.get("action_forecast") if isinstance(cached.get("action_forecast"), dict) else {}
    global_reg = cached.get("global_regime") if isinstance(cached.get("global_regime"), dict) else {}
    sector = cached.get("sector_regime") if isinstance(cached.get("sector_regime"), dict) else {}
    regime_block = sector.get("regime") if isinstance(sector.get("regime"), dict) else {}
    try:
        sign = int(point.get("expected_return_sign") or 0)
    except (TypeError, ValueError):
        sign = 0
    rec = str(action.get("recommendation") or "").strip().lower()
    cal = cached.get("calibrated_confidence")
    try:
        cal_f = float(cal) if cal is not None else None
    except (TypeError, ValueError):
        cal_f = None
    hmm = (
        str(regime_block.get("dominant_regime") or "").strip()
        or str(global_reg.get("dominant_regime") or "").strip()
        or None
    )
    mom = sector.get("sector_momentum")
    try:
        mom_f = float(mom) if mom is not None else None
    except (TypeError, ValueError):
        mom_f = None
    return HierarchyHint(
        ticker=sym,
        recommendation=rec,
        expected_sign=sign if sign in (-1, 0, 1) else 0,
        calibrated_confidence=cal_f,
        hmm_or_global_regime=hmm,
        sector_momentum=mom_f,
        cache_hit=True,
    )


def apply_hint_to_direction(
    *,
    direction: str,
    confidence: float,
    hint: HierarchyHint | None,
) -> tuple[str, float]:
    """Hierarchy may set direction when ML is weak or silent; AVOID never promotes."""
    if hint is None or not hint.cache_hit or hint.is_avoid:
        return direction, confidence
    pref = hint.preferred_direction
    if not pref:
        return direction, confidence
    if direction == "neutral":
        seed = hint.calibrated_confidence if hint.calibrated_confidence is not None else 0.48
        return pref, min(0.72, max(confidence, seed * 0.85 + 0.12))
    if pref != direction and confidence < 0.58:
        seed = hint.calibrated_confidence if hint.calibrated_confidence is not None else 0.5
        return pref, min(0.64, max(0.40, seed * 0.7 + 0.18))
    return direction, confidence


def apply_hint_to_confidence(
    *,
    direction: str,
    confidence: float,
    hint: HierarchyHint | None,
) -> float:
    if hint is None or not hint.cache_hit:
        return confidence
    adj = confidence
    pref = hint.preferred_direction
    if pref and direction in {"long", "short"}:
        if pref == direction:
            adj += 0.06
        else:
            adj -= 0.08
    if hint.is_avoid:
        adj -= 0.12
    elif hint.is_wait:
        adj -= 0.02
    if hint.calibrated_confidence is not None:
        adj = 0.7 * adj + 0.3 * max(0.0, min(1.0, hint.calibrated_confidence))
    if hint.sector_momentum is not None:
        mom = max(-1.0, min(1.0, hint.sector_momentum))
        if direction == "long":
            adj += 0.03 * mom
        elif direction == "short":
            adj -= 0.03 * mom
    return min(max(adj, 0.0), 0.95)
