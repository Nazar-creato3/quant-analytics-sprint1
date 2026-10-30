"""GA16-333: ensemble shadow failures must not put exception text in maneuver meta."""
from __future__ import annotations

from unittest.mock import patch

from app.services.risk.ensemble_shadow import run_shadow


def test_shadow_failure_hides_exception_text(monkeypatch) -> None:
    monkeypatch.setenv("MANEUVER_SHADOW_FORCE", "1")
    closes = [100.0 + i * 0.1 for i in range(40)]

    class Boom:
        def compute(self, *_a, **_k):
            raise RuntimeError("torch CUDA secret path")

    with patch(
        "app.services.forecast.ensemble.get_ensemble_forecast_engine",
        return_value=Boom(),
    ):
        row = run_shadow(
            "SBER",
            closes,
            clf_direction="long",
            clf_confidence=0.7,
        )
    assert row is not None
    assert row["used_for_maneuver"] is False
    assert row["error"] == "нет данных"
    assert "torch" not in str(row).lower()
    assert "secret" not in str(row).lower()
