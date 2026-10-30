"""Client IP resolution behind reverse proxies (Caddy / nginx)."""
from __future__ import annotations

import ipaddress

from starlette.requests import Request

from app.core.config import settings


def _peer_ip(request: Request) -> str | None:
    if request.client is None:
        return None
    return request.client.host


def _parse_forwarded_for(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _is_trusted_proxy(ip: str | None) -> bool:
    if not ip:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in network for network in settings.trusted_proxy_networks)


def get_client_ip(request: Request) -> str | None:
    """
    Resolve the original client IP when the app sits behind a reverse proxy.

    Only trusts ``X-Forwarded-For`` / ``X-Real-IP`` when the immediate peer
    (``request.client.host``) is in ``TRUSTED_PROXY_CIDRS``. Without this,
    every browser request can collapse to the Docker bridge IP (e.g.
    ``172.18.0.x``) and share one rate-limit bucket.
    """
    peer = _peer_ip(request)
    if not _is_trusted_proxy(peer):
        return peer

    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        parts = _parse_forwarded_for(forwarded)
        if parts:
            return parts[0]

    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()

    return peer
