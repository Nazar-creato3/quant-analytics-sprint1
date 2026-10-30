"""Which exchange hosts a user-supplied base_url may point to.

The connect form accepts a base_url (testnet vs main API). Without a check the
server would send signed requests to any address the user typed, including
internal services (vault, redis, cloud metadata): server-side request forgery.
"""
from __future__ import annotations

from urllib.parse import urlparse

ALLOWED_HOSTS: frozenset[str] = frozenset(
    {
        "api.bybit.com",
        "api-testnet.bybit.com",
        "api.bytick.com",
        "api.mexc.com",
        "api.binance.com",
        "testnet.binance.vision",
        "paper-api.alpaca.markets",
        "api.alpaca.markets",
    }
)


class BaseUrlRejected(ValueError):
    pass


def checked_base_url(raw: str | None) -> str | None:
    """Return a normalised https URL on an allowed exchange host, or raise."""
    if raw is None or not raw.strip():
        return None
    parsed = urlparse(raw.strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host not in ALLOWED_HOSTS or parsed.username or parsed.password:
        raise BaseUrlRejected("Адрес API биржи не поддерживается")
    if parsed.port not in (None, 443):
        raise BaseUrlRejected("Адрес API биржи не поддерживается")
    return f"https://{host}"
