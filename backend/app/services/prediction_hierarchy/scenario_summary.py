"""Statistical narrative for top scenario probabilities (market + per-asset)."""
from __future__ import annotations

from typing import Mapping, Sequence

CLOSE_SCENARIO_THRESHOLD = 0.05


def _pct(probability: float) -> str:
    return f"{round(max(0.0, min(1.0, probability)) * 100.0, 1)}%"


def rank_scenario_probabilities(
    distribution: Mapping[str, float],
    *,
    label_ru: Mapping[str, str] | None = None,
) -> list[tuple[str, str, float]]:
    """Return (key, label_ru, probability) sorted descending."""
    labels = label_ru or {}
    items = [
        (key, labels.get(key, key.replace("_", " ")), float(prob))
        for key, prob in distribution.items()
        if prob is not None and float(prob) > 0
    ]
    return sorted(items, key=lambda row: row[2], reverse=True)


def describe_top_scenarios(
    scenarios: Sequence[tuple[str, str, float]],
    *,
    context_prefix: str = "",
    close_threshold: float = CLOSE_SCENARIO_THRESHOLD,
    impacts: Mapping[str, float] | None = None,
) -> str:
    """Describe the largest scenario; include 2nd when probabilities tie or differ < 5%."""
    if not scenarios:
        return ""

    ranked = sorted(scenarios, key=lambda row: row[2], reverse=True)
    top_key, top_label, top_prob = ranked[0]
    impact_clause = ""
    if impacts and top_key in impacts and impacts[top_key] is not None:
        impact_clause = f", ожидаемый эффект {impacts[top_key] * 100:+.1f}%"

    parts = [
        f"Наиболее вероятный сценарий — «{top_label}» ({_pct(top_prob)}{impact_clause})."
    ]

    if len(ranked) >= 2:
        second_key, second_label, second_prob = ranked[1]
        diff = top_prob - second_prob
        if diff < close_threshold:
            second_impact = ""
            if impacts and second_key in impacts and impacts[second_key] is not None:
                second_impact = f", эффект {impacts[second_key] * 100:+.1f}%"
            parts.append(
                f"Второй по вероятности — «{second_label}» ({_pct(second_prob)}{second_impact}); "
                f"разрыв {_pct(diff)} — исходы статистически близки."
            )

    body = " ".join(parts)
    if context_prefix:
        return f"{context_prefix.rstrip()} {body}"
    return body


def describe_narrative_archetypes(
    items: Sequence[tuple[str, str, float, float | None]],
    *,
    symbol: str | None = None,
    close_threshold: float = CLOSE_SCENARIO_THRESHOLD,
) -> str:
    """Build per-asset summary from (key, label_ru, probability, impact) tuples."""
    if not items:
        return ""

    prefix = f"По {symbol}:" if symbol else "По инструменту:"
    scenarios = [(key, label, prob) for key, label, prob, _ in items]
    impacts = {key: impact for key, _, _, impact in items if impact is not None}
    return describe_top_scenarios(
        scenarios,
        context_prefix=prefix,
        close_threshold=close_threshold,
        impacts=impacts,
    )
