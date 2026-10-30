"""Where a model call is allowed to go (Academy A1).

The provider id stays in Settings. On-prem mode refuses a public host
before any HTTP client is opened. This module does not choose a vendor.
"""
from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

from app.core.config import settings

# Docker / loopback names only. A public DNS name is not treated as on-prem.
_LOCAL_NAMES = frozenset(
    {
        "localhost",
        "llm",
        "postgres",
        "redis",
        "backend",
        "apex-onprem-backend",
        "apex-onprem-postgres",
        "apex-onprem-redis",
    }
)


class OnpremPublicBlocked(RuntimeError):
    """On-prem mode was asked to call a host that is not local or private."""


def llm_onprem_active() -> bool:
    provider = str(getattr(settings, "LLM_PROVIDER", "") or "").strip().lower()
    return bool(getattr(settings, "LLM_ONPREM", False)) or provider == "onprem"


def host_is_non_public(url: str) -> bool:
    parsed = urlparse((url or "").strip())
    host = (parsed.hostname or "").strip().lower()
    if parsed.scheme not in {"http", "https"} or not host:
        return False
    if host in _LOCAL_NAMES or host.endswith((".local", ".internal")):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return bool(address.is_private or address.is_loopback or address.is_link_local)


def ensure_model_url(url: str) -> str:
    """Return the URL, or raise before a socket if on-prem would leave the host."""
    cleaned = (url or "").strip()
    if llm_onprem_active() and not host_is_non_public(cleaned):
        raise OnpremPublicBlocked("on-prem refuses a public model URL")
    return cleaned
