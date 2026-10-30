"""News impact probability classifier — historical analogs + factor alignment."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from app.services.quant_math import historical_volatility, log_return

# Prior for Bayesian calibration when few historical analogs exist.
DEFAULT_PRIOR_ALPHA = 2.0
DEFAULT_PRIOR_BETA = 5.0

# Keyword → factor name mapping (Prompt 19 factor_exposure names).
NEWS_KEYWORD_TO_FACTOR: dict[str, tuple[str, ...]] = {
    "rate": ("rates_sensitivity",),
    "rates": ("rates_sensitivity",),
    "fed": ("rates_sensitivity", "macro_shock_sensitivity"),
    "interest": ("rates_sensitivity",),
    "cpi": ("macro_shock_sensitivity", "rates_sensitivity"),
    "inflation": ("macro_shock_sensitivity", "rates_sensitivity"),
    "unemployment": ("macro_shock_sensitivity",),
    "oil": ("commodity_sensitivity",),
    "brent": ("commodity_sensitivity",),
    "crude": ("commodity_sensitivity",),
    "energy": ("commodity_sensitivity", "sector_factor"),
    "dollar": ("fx_sensitivity",),
    "dxy": ("fx_sensitivity",),
    "fx": ("fx_sensitivity",),
    "currency": ("fx_sensitivity",),
    "earnings": ("market_beta", "growth"),
    "revenue": ("growth", "market_beta"),
    "guidance": ("growth", "market_beta"),
    "dividend": ("value", "market_beta"),
    "sanction": ("macro_shock_sensitivity", "fx_sensitivity"),
    "war": ("macro_shock_sensitivity", "volatility_factor"),
    "vix": ("volatility_factor", "market_beta"),
    "liquidity": ("volatility_factor",),
}

TOPIC_TAG_PATTERN = re.compile(r"[a-z0-9_]+")


@dataclass(frozen=True, slots=True)
class NewsImpactAnalog:
    """Historical record used for analog matching."""

    topic_tags: tuple[str, ...]
    strong_move: bool
    predicted_probability: float | None = None


@dataclass(frozen=True, slots=True)
class NewsImpactProbabilityResult:
    """Classifier output for a news item against an instrument."""

    probability: float
    analog_probability: float
    factor_alignment: float
    daily_volatility: float
    sigma_threshold: float
    topic_tags: tuple[str, ...]
    matched_factors: tuple[str, ...]
    analog_count: int
    strong_analog_count: int


def normalize_tags(tags: Sequence[str] | None) -> tuple[str, ...]:
    """Normalize topic tags for matching."""
    if not tags:
        return ()
    normalized = sorted({value.strip().lower() for value in tags if value and value.strip()})
    return tuple(normalized)


def extract_topic_tags(article: Any) -> tuple[str, ...]:
    """Extract topic tags from connector/app news rows."""
    raw_tags = getattr(article, "tags", None) or []
    if isinstance(raw_tags, str):
        raw_tags = [part.strip() for part in raw_tags.split(",") if part.strip()]
    tags = normalize_tags(raw_tags)

    if tags:
        return tags

    title = getattr(article, "title", "") or ""
    summary = getattr(article, "summary", "") or getattr(article, "description", "") or ""
    text = f"{title} {summary}".lower()
    inferred: set[str] = set()
    for keyword in NEWS_KEYWORD_TO_FACTOR:
        if keyword in text:
            inferred.add(keyword)
    return normalize_tags(tuple(inferred))


def infer_news_factors(topic_tags: Sequence[str]) -> tuple[str, ...]:
    """Map news tags/keywords to factor names."""
    factors: set[str] = set()
    for tag in topic_tags:
        for factor in NEWS_KEYWORD_TO_FACTOR.get(tag, ()):
            factors.add(factor)
    return tuple(sorted(factors))


def tag_overlap_score(left: Sequence[str], right: Sequence[str]) -> float:
    """Jaccard similarity between two tag sets."""
    a = set(left)
    b = set(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def bayesian_strong_move_probability(
    *,
    strong_count: int,
    total_count: int,
    prior_alpha: float = DEFAULT_PRIOR_ALPHA,
    prior_beta: float = DEFAULT_PRIOR_BETA,
) -> float:
    """Beta-Binomial posterior mean for P(strong_move)."""
    if total_count < 0 or strong_count < 0 or strong_count > total_count:
        raise ValueError("Invalid analog counts for Bayesian update.")
    alpha = prior_alpha + strong_count
    beta = prior_beta + (total_count - strong_count)
    return alpha / (alpha + beta)


def compute_analog_probability(
    topic_tags: Sequence[str],
    history: Sequence[NewsImpactAnalog],
    *,
    min_overlap: float = 0.25,
    prior_alpha: float = DEFAULT_PRIOR_ALPHA,
    prior_beta: float = DEFAULT_PRIOR_BETA,
) -> tuple[float, int, int]:
    """Estimate impact probability from similar historical news."""
    strong_count = 0
    total_count = 0
    for record in history:
        overlap = tag_overlap_score(topic_tags, record.topic_tags)
        if overlap < min_overlap:
            continue
        total_count += 1
        if record.strong_move:
            strong_count += 1

    probability = bayesian_strong_move_probability(
        strong_count=strong_count,
        total_count=total_count,
        prior_alpha=prior_alpha,
        prior_beta=prior_beta,
    )
    return round(probability, 4), total_count, strong_count


def compute_factor_alignment(
    topic_tags: Sequence[str],
    factor_exposures: Mapping[str, float],
) -> tuple[float, tuple[str, ...]]:
    """Score how closely news topics align with instrument factor betas."""
    news_factors = infer_news_factors(topic_tags)
    if not news_factors or not factor_exposures:
        return 0.0, news_factors

    scores: list[float] = []
    matched: list[str] = []
    for factor in news_factors:
        beta = factor_exposures.get(factor)
        if beta is None:
            continue
        magnitude = min(1.0, abs(float(beta)))
        if magnitude <= 0.0:
            continue
        scores.append(magnitude)
        matched.append(factor)

    if not scores:
        return 0.0, tuple(matched)

    alignment = sum(scores) / len(scores)
    return round(min(1.0, alignment), 4), tuple(matched)


def compute_daily_volatility_from_prices(prices: Sequence[float]) -> float:
    """Baseline daily volatility from close prices via log returns."""
    if len(prices) < 2:
        return 0.0
    returns = [log_return(prices[index], prices[index - 1]) for index in range(1, len(prices))]
    return historical_volatility(returns)


def compute_actual_move_sigma(
    *,
    price_at_news: float,
    price_after: float,
    daily_volatility: float,
) -> tuple[float, float]:
    """Return (move_pct, move_sigma) using daily vol as baseline."""
    if price_at_news <= 0.0 or price_after <= 0.0:
        return 0.0, 0.0
    move_pct = abs((price_after - price_at_news) / price_at_news)
    if daily_volatility <= 0.0:
        return round(move_pct, 6), 0.0
    move_sigma = move_pct / daily_volatility
    return round(move_pct, 6), round(move_sigma, 4)


def is_strong_move(move_sigma: float, *, sigma_threshold: float) -> bool:
    return move_sigma >= sigma_threshold


def compute_news_impact_probability(
    *,
    topic_tags: Sequence[str],
    factor_exposures: Mapping[str, float],
    history: Sequence[NewsImpactAnalog],
    daily_volatility: float,
    sigma_threshold: float = 2.0,
    analog_weight: float = 0.55,
    factor_weight: float = 0.45,
    min_overlap: float = 0.25,
) -> NewsImpactProbabilityResult:
    """Combine analog history and factor alignment into impact probability."""
    tags = normalize_tags(topic_tags)
    analog_probability, analog_count, strong_count = compute_analog_probability(
        tags,
        history,
        min_overlap=min_overlap,
    )
    factor_alignment, matched_factors = compute_factor_alignment(tags, factor_exposures)

    total_weight = analog_weight + factor_weight
    if total_weight <= 0.0:
        raise ValueError("analog_weight + factor_weight must be > 0.")

    probability = (
        analog_weight * analog_probability + factor_weight * factor_alignment
    ) / total_weight
    probability = max(0.0, min(1.0, probability))

    return NewsImpactProbabilityResult(
        probability=round(probability, 4),
        analog_probability=analog_probability,
        factor_alignment=factor_alignment,
        daily_volatility=round(daily_volatility, 6),
        sigma_threshold=sigma_threshold,
        topic_tags=tags,
        matched_factors=matched_factors,
        analog_count=analog_count,
        strong_analog_count=strong_count,
    )


def update_posterior_from_feedback(
    *,
    predicted_probability: float,
    strong_move: bool,
    prior_alpha: float = DEFAULT_PRIOR_ALPHA,
    prior_beta: float = DEFAULT_PRIOR_BETA,
) -> float:
    """Simple Bayesian update after observing realized move."""
    alpha = prior_alpha + (1 if strong_move else 0)
    beta = prior_beta + (0 if strong_move else 1)
    posterior = alpha / (alpha + beta)
    # Blend classifier output with observed outcome for calibration storage.
    blended = 0.5 * predicted_probability + 0.5 * posterior
    return round(max(0.0, min(1.0, blended)), 4)


def sentiment_magnitude_boost(sentiment_score: float | None) -> float:
    """Optional boost when sentiment magnitude is extreme."""
    if sentiment_score is None:
        return 0.0
    return min(0.15, abs(float(sentiment_score)) * 0.1)
