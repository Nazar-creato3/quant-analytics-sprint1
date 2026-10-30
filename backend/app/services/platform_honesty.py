"""Platform honesty constants — credible accuracy ceilings and disclosure."""
from __future__ import annotations

HONESTY_OVER_FABRICATION = "honesty_over_fabrication"

# Published modern ensemble directional benchmark (not an internal target to beat).
ENSEMBLE_ACCURACY_REFERENCE = 0.635

# Honest ceiling shown to users/investors — replaces legacy 70% aspirational copy.
ENSEMBLE_ACCURACY_CEILING = 0.635

# Deprecated optimistic marketing figure — kept for migration/disclosure only.
LEGACY_OPTIMISTIC_ENSEMBLE_TARGET = 0.70

NEWS_CALENDAR_SHARED_SOURCE = "finnhub"

ACCURACY_DISCLOSURE_RU = (
    "Ориентир точности ансамбля ~63.5% (современный опубликованный бенчмарк), "
    "не 70%. Мы показываем Wilson CI и sample size, а не «уверенные» проценты без n."
)
