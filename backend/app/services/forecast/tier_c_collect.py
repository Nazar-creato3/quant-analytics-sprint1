"""Merge C extras without calling vendors that are not armed or have no fetcher."""

from __future__ import annotations

from app.core.logging import get_logger
from app.services.forecast.tier_c_capabilities import should_call_vendor
from app.services.forecast.tier_c_schema import EMPTY_TIER_C_EXTRAS
from app.services.forecast.tier_c_store import load_tier_c_extras

logger = get_logger(__name__)

# Live HTTP adapters are registered here when written. Empty on purpose.
_LIVE_FETCHERS: dict[str, object] = {}


def collect_tier_c_extras(symbol: str) -> dict[str, float]:
    extras = dict(EMPTY_TIER_C_EXTRAS)
    extras.update(load_tier_c_extras(symbol))
    for name, fetcher in _LIVE_FETCHERS.items():
        if not should_call_vendor(name):
            continue
        try:
            live = fetcher(symbol)  # type: ignore[operator]
        except Exception as exc:
            logger.warning("tier_c_live_fetch_skipped", vendor=name, error=str(exc)[:160])
            continue
        if isinstance(live, dict):
            extras.update({k: float(v) for k, v in live.items() if k in extras})
            if any(abs(float(extras[k])) > 1e-12 for k in extras if k != "c_tier_present"):
                extras["c_tier_present"] = 1.0
    return extras
