"""C-vendor arming: keys may sit in env, but idle vendors never get a network call.

Live HTTP is a separate switch. Default off — dropping a token must not start
quota burn until a fetcher is registered and TIER_C_LIVE_FETCH is true.
Receiving data = local PIT store, which costs no vendor calls.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import settings


@dataclass(frozen=True, slots=True)
class TierCVendor:
    name: str
    setting_attr: str
    feature_prefix: str


VENDORS: tuple[TierCVendor, ...] = (
    TierCVendor("sharadar", "SHARADAR_API_KEY", "c_value"),
    TierCVendor("nasdaq_data_link", "NASDAQ_DATA_LINK_API_KEY", "c_value"),
    TierCVendor("ravenpack", "RAVENPACK_API_KEY", "c_news"),
    TierCVendor("databento_sip", "DATABENTO_API_KEY", "c_sip"),
)


def _key_present(attr: str) -> bool:
    raw = getattr(settings, attr, "") or ""
    return bool(str(raw).strip())


def vendor_armed(name: str) -> bool:
    for vendor in VENDORS:
        if vendor.name == name:
            return _key_present(vendor.setting_attr)
    return False


def armed_vendors() -> tuple[str, ...]:
    return tuple(v.name for v in VENDORS if _key_present(v.setting_attr))


def live_fetch_allowed() -> bool:
    """Even armed vendors stay silent unless this is on and a fetcher exists."""
    return bool(getattr(settings, "TIER_C_LIVE_FETCH", False))


def should_call_vendor(name: str) -> bool:
    return live_fetch_allowed() and vendor_armed(name)
