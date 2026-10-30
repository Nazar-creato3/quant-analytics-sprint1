"""Reserved C-tier feature slots. Always in the vector; 0 until a local PIT row exists."""

from __future__ import annotations

# Names are stable so a later LightGBM can learn them without a schema migration.
TIER_C_FEATURE_COLUMNS: tuple[str, ...] = (
    "c_value_yield",
    "c_value_book",
    "c_quality",
    "c_growth",
    "c_leverage",
    "c_news_tone",
    "c_news_novelty",
    "c_news_volume",
    "c_sip_spread",
    "c_tier_present",
)

EMPTY_TIER_C_EXTRAS: dict[str, float] = {k: 0.0 for k in TIER_C_FEATURE_COLUMNS}
