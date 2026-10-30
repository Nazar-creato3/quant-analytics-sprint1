"""Default forecast view configuration (Step 4 — product framing)."""
from __future__ import annotations

# No single-name horizon sustained >52-53% on 2y walk-forward (see horizon benchmark).
# Default UI emphasizes sector/basket relative view; single-name direction is low-confidence.
DEFAULT_FORECAST_VIEW = "sector_relative"
DEFAULT_INTERVAL_HORIZON_DAYS = 10
SINGLE_NAME_HEADLINE_HORIZON_DAYS = 5
SUSTAINED_EDGE_THRESHOLD = 0.52
MIN_SAMPLES_FOR_EDGE_CLAIM = 50

SINGLE_NAME_LOW_CONFIDENCE_MESSAGE_RU = (
    "Краткосрочное направление отдельной бумаги — низкая уверенность; "
    "ориентируйтесь на секторный/корзинный контекст."
)

INSUFFICIENT_EDGE_MESSAGE_RU = (
    "Недостаточно устойчивого преимущества на выбранном горизонте — "
    "прогноз носит справочный характер."
)
