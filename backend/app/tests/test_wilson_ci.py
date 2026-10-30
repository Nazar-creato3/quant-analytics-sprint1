"""Unit tests for Wilson score confidence intervals."""
from __future__ import annotations

import pytest

from app.utils.wilson_ci import (
    format_accuracy_with_ci_ru,
    wilson_ci,
    wilson_ci_from_rate,
)


def test_wilson_ci_zero_trials_returns_none():
    assert wilson_ci(0, 0) is None


def test_wilson_ci_perfect_accuracy():
    interval = wilson_ci(10, 10)
    assert interval is not None
    assert interval.proportion == 1.0
    assert interval.ci_low > 0.69
    assert interval.ci_high == 1.0


def test_wilson_ci_half_accuracy_reasonable_bounds():
    interval = wilson_ci(50, 100)
    assert interval is not None
    assert 0.39 <= interval.ci_low <= 0.45
    assert 0.55 <= interval.ci_high <= 0.61
    assert abs(interval.proportion - 0.5) < 0.01


def test_wilson_ci_invalid_successes_raises():
    with pytest.raises(ValueError):
        wilson_ci(11, 10)


def test_wilson_ci_from_rate():
    interval = wilson_ci_from_rate(0.467, 142)
    assert interval is not None
    assert interval.trials == 142
    assert 0.38 <= interval.ci_low <= 0.42
    assert 0.51 <= interval.ci_high <= 0.56


def test_format_accuracy_with_ci_ru():
    text = format_accuracy_with_ci_ru(0.467, ci_low=0.38, ci_high=0.56, sample_size=142)
    assert "46.7%" in text
    assert "95% ДИ" in text
    assert "n=142" in text
