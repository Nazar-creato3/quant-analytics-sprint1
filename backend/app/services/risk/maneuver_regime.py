"""Apply already-computed market regime + BOCPD to confidence/size — not labels only."""
from __future__ import annotations

from typing import Any, Sequence

from app.core.logging import get_logger

logger = get_logger(__name__)


def regime_size_mult(market_regime: dict[str, Any] | None) -> float | None:
    if not market_regime:
        return None
    raw = market_regime.get("size_mult")
    if raw is None:
        return None
    try:
        return max(0.0, min(1.0, float(raw)))
    except (TypeError, ValueError):
        return None


def regime_blocks_new_risk(market_regime: dict[str, Any] | None) -> bool:
    if not market_regime:
        return False
    if market_regime.get("alpha_on") is False:
        return True
    mult = regime_size_mult(market_regime)
    return mult is not None and mult <= 0.0


def detect_bocpd(closes: Sequence[float], *, hmm_label: str | None = None) -> dict[str, Any]:
    """One-shot market-anchor BOCPD. Do not run per ticker."""
    if len(closes) < 22:
        return {}
    try:
        from app.services.forecast.bocpd import combine_bocpd_with_hmm

        result = combine_bocpd_with_hmm(list(closes), hmm_label, hmm_confidence=0.6)
    except Exception as exc:
        logger.debug("bocpd_skip", error=str(exc)[:120])
        return {}
    return result.to_dict()


def scale_confidence_from_bocpd(confidence: float, meta: dict[str, Any] | None) -> float:
    if not meta:
        return confidence
    try:
        cp = float(meta.get("changepoint_probability") or 0.0)
        uncertain = bool(meta.get("regime_uncertain"))
    except (TypeError, ValueError):
        return confidence
    adj = float(confidence)
    if cp >= 0.45 or uncertain:
        adj *= max(0.45, 1.0 - 0.4 * cp)
    return max(0.0, min(0.95, adj))


def apply_bocpd_to_confidence(
    confidence: float,
    closes: Sequence[float],
    *,
    hmm_label: str | None = None,
) -> tuple[float, dict[str, Any]]:
    meta = detect_bocpd(closes, hmm_label=hmm_label)
    if not meta:
        return confidence, {}
    adj = scale_confidence_from_bocpd(confidence, meta)
    out = dict(meta)
    out["confidence_before"] = float(confidence)
    out["confidence_after"] = adj
    out["confidence_scaled"] = adj + 1e-12 < float(confidence)
    return adj, out
