"""Greedy diversified selection for top-N maneuver slots (spec A.2b)."""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

from app.core.logging import get_logger
from app.services.macro.sector_seed import sector_for_symbol

if TYPE_CHECKING:
    from app.services.risk.maneuver_generator import ManeuverCandidate

logger = get_logger(__name__)

DEFAULT_MAX_SECTOR_COUNT = 2
DEFAULT_FACTOR_SIMILARITY = 0.80
RELAXED_FACTOR_SIMILARITY = 0.92


def _sector_key(ticker: str) -> str:
    mapped = sector_for_symbol(ticker)
    if mapped:
        return mapped[0]
    return "unknown"


def _factor_vector(candidate: "ManeuverCandidate") -> list[float]:
    """Build a factor-exposure proxy from ML features (no async DB needed)."""
    features = candidate.prediction.features_used or {}
    return [
        float(features.get("roc_5", 0.0)) / 100.0,
        float(features.get("roc_20", 0.0)) / 100.0,
        float(features.get("price_vs_sma20", 0.0)),
        float(features.get("price_vs_sma50", 0.0)),
        float(features.get("volatility_20d", 0.0)),
        float(features.get("atr_pct", 0.0)),
        float(features.get("bb_position", 0.5)) - 0.5,
        float(features.get("volume_ratio", 1.0)) - 1.0,
        float(features.get("rsi_14", 50.0)) / 100.0 - 0.5,
        candidate.news_sentiment,
        candidate.macro_score,
        candidate.event_score,
    ]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a <= 1e-12 or norm_b <= 1e-12:
        return 0.0
    return dot / (norm_a * norm_b)


def _passes_diversity(
    candidate: "ManeuverCandidate",
    selected: list["ManeuverCandidate"],
    *,
    max_sector_count: int,
    max_similarity: float,
) -> bool:
    sector = _sector_key(candidate.ticker)
    sector_count = sum(1 for s in selected if _sector_key(s.ticker) == sector)
    if sector_count >= max_sector_count:
        return False

    vec = _factor_vector(candidate)
    for existing in selected:
        sim = cosine_similarity(vec, _factor_vector(existing))
        if sim > max_similarity:
            return False
    return True


def select_diversified_candidates(
    ranked: list["ManeuverCandidate"],
    *,
    target: int,
    max_sector_count: int = DEFAULT_MAX_SECTOR_COUNT,
    max_similarity: float = DEFAULT_FACTOR_SIMILARITY,
) -> list["ManeuverCandidate"]:
    """
    Greedy diversified pick from score-ranked candidates.

    Walks the ranked list and adds tickers that pass sector and factor-similarity
    constraints. Relaxes similarity threshold if not enough candidates remain.
    """
    if not ranked or target <= 0:
        return []

    selected: list["ManeuverCandidate"] = []
    used_tickers: set[str] = set()
    threshold = max_similarity

    while len(selected) < target and threshold <= RELAXED_FACTOR_SIMILARITY + 1e-9:
        progress = False
        for candidate in ranked:
            if len(selected) >= target:
                break
            if candidate.ticker in used_tickers:
                continue
            if candidate.prediction.direction == "neutral":
                continue
            if not _passes_diversity(
                candidate,
                selected,
                max_sector_count=max_sector_count,
                max_similarity=threshold,
            ):
                continue
            selected.append(candidate)
            used_tickers.add(candidate.ticker)
            progress = True

        if len(selected) >= target:
            break
        if not progress:
            threshold = round(threshold + 0.04, 4)
        elif len(selected) < target:
            threshold = round(threshold + 0.02, 4)

    if len(selected) < target:
        relaxed = max_similarity
        while len(selected) < target and relaxed <= RELAXED_FACTOR_SIMILARITY + 1e-9:
            added_any = False
            for candidate in ranked:
                if len(selected) >= target:
                    break
                if candidate.ticker in used_tickers:
                    continue
                if candidate.prediction.direction == "neutral":
                    continue
                if not _passes_diversity(
                    candidate,
                    selected,
                    max_sector_count=max_sector_count,
                    max_similarity=relaxed,
                ):
                    continue
                selected.append(candidate)
                used_tickers.add(candidate.ticker)
                added_any = True
            if not added_any:
                relaxed = round(relaxed + 0.04, 4)
            else:
                relaxed = round(relaxed + 0.02, 4)

    logger.debug(
        "Diversified selection",
        input=len(ranked),
        selected=len(selected),
        target=target,
        final_threshold=threshold,
    )
    return selected
