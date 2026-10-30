"""Bull / Base / Bear scenario framing for Forecast UI."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from app.services.prediction_hierarchy.types import ScenarioForecastItem


ARCHETYPE_TO_SCENARIO = {
    "optimistic": "bull",
    "realistic": "base",
    "pessimistic": "bear",
    "classic": "base",
}

SCENARIO_LABELS_RU = {
    "bull": "Бычий сценарий",
    "base": "Базовый сценарий",
    "bear": "Медвежий сценарий",
}


@dataclass(frozen=True, slots=True)
class BullBaseBearScenario:
    key: str  # bull | base | bear
    label_ru: str
    probability: float
    expected_return: float | None
    narrative: str

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "label_ru": self.label_ru,
            "probability": self.probability,
            "expected_return": self.expected_return,
            "narrative": self.narrative,
        }


def build_bull_base_bear(
    *,
    narrative_scenarios: Mapping[str, float] | None = None,
    stress_scenarios: Sequence[ScenarioForecastItem] | None = None,
    median_return: float = 0.0,
    ensemble_bull_return: float | None = None,
    ensemble_bear_return: float | None = None,
) -> tuple[BullBaseBearScenario, ...]:
    """Map narrative archetypes + stress to bull/base/bear trio."""
    weights: dict[str, float] = {"bull": 0.0, "base": 0.0, "bear": 0.0}
    narratives: dict[str, str] = {}

    if narrative_scenarios:
        for archetype, prob in narrative_scenarios.items():
            key = ARCHETYPE_TO_SCENARIO.get(archetype, "base")
            weights[key] += float(prob)
            if archetype == "optimistic":
                narratives["bull"] = "Благоприятный импульс при сдержанной волатильности."
            elif archetype == "pessimistic":
                narratives["bear"] = "Негативный хвост: рост vol, bearish impulse или stress-режим."
            elif archetype == "realistic":
                narratives["base"] = "Базовый случай: медианный ensemble-прогноз."
            elif archetype == "classic":
                narratives.setdefault("base", "Исторический / mean-reversion путь.")

    if stress_scenarios:
        for item in stress_scenarios:
            if item.impact < -0.03:
                weights["bear"] += item.probability * 0.5
                narratives.setdefault("bear", item.impact_narrative_ru or item.label_ru)
            elif item.impact > 0.03:
                weights["bull"] += item.probability * 0.5
                narratives.setdefault("bull", item.impact_narrative_ru or item.label_ru)

    total = sum(weights.values())
    if total <= 0:
        weights = {"bull": 0.25, "base": 0.50, "bear": 0.25}
    else:
        weights = {k: v / total for k, v in weights.items()}

    returns = {
        "bull": ensemble_bull_return if ensemble_bull_return is not None else median_return * 1.5,
        "base": median_return,
        "bear": ensemble_bear_return if ensemble_bear_return is not None else median_return * -1.2,
    }

    return tuple(
        BullBaseBearScenario(
            key=key,
            label_ru=SCENARIO_LABELS_RU[key],
            probability=round(weights[key], 3),
            expected_return=round(returns[key], 4) if returns[key] is not None else None,
            narrative=narratives.get(key, SCENARIO_LABELS_RU[key]),
        )
        for key in ("base", "bull", "bear")
    )
