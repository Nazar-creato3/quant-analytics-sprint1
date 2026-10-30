"""Tests for platform honesty constants."""
from __future__ import annotations

from app.services.platform_honesty import (
    ENSEMBLE_ACCURACY_CEILING,
    ENSEMBLE_ACCURACY_REFERENCE,
    LEGACY_OPTIMISTIC_ENSEMBLE_TARGET,
)


def test_honest_ceiling_not_seventy_percent():
    assert ENSEMBLE_ACCURACY_CEILING == 0.635
    assert ENSEMBLE_ACCURACY_REFERENCE == 0.635
    assert LEGACY_OPTIMISTIC_ENSEMBLE_TARGET == 0.70
