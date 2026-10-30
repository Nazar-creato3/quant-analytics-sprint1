"""Tests for scenario probability narrative helpers."""
from __future__ import annotations

from app.services.prediction_hierarchy.scenario_summary import (
    CLOSE_SCENARIO_THRESHOLD,
    describe_narrative_archetypes,
    describe_top_scenarios,
    rank_scenario_probabilities,
)


class TestScenarioSummary:
    def test_describes_largest_scenario_only_when_gap_wide(self):
        text = describe_top_scenarios(
            [
                ("realistic", "Реалистичный", 0.42),
                ("pessimistic", "Пессимистичный", 0.28),
            ],
        )
        assert "Наиболее вероятный" in text
        assert "Реалистичный" in text
        assert "42" in text
        assert "Второй по вероятности" not in text

    def test_describes_second_scenario_when_within_five_percent(self):
        text = describe_top_scenarios(
            [
                ("optimistic", "Оптимистичный", 0.31),
                ("realistic", "Реалистичный", 0.29),
            ],
            close_threshold=CLOSE_SCENARIO_THRESHOLD,
        )
        assert "Оптимистичный" in text
        assert "Реалистичный" in text
        assert "Второй по вероятности" in text
        assert "близки" in text

    def test_narrative_archetypes_include_impact(self):
        text = describe_narrative_archetypes(
            [
                ("realistic", "Реалистичный", 0.40, 0.012),
                ("pessimistic", "Пессимистичный", 0.38, -0.025),
            ],
            symbol="AAPL",
        )
        assert "AAPL" in text
        assert "Реалистичный" in text
        assert "Второй по вероятности" in text

    def test_rank_scenario_probabilities_orders_descending(self):
        ranked = rank_scenario_probabilities(
            {"risk_on": 0.2, "risk_off": 0.45, "macro_uncertainty": 0.35},
            label_ru={"risk_off": "risk-off", "macro_uncertainty": "макро"},
        )
        assert ranked[0][0] == "risk_off"
        assert ranked[1][0] == "macro_uncertainty"
