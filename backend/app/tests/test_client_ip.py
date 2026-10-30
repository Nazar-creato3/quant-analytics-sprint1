"""Tests for trusted-proxy client IP resolution."""
from __future__ import annotations

from starlette.requests import Request

from app.core.client_ip import get_client_ip


def _request(
    *,
    peer: str = "172.18.0.2",
    headers: list[tuple[bytes, bytes]] | None = None,
) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": headers or [],
        "client": (peer, 12345),
        "server": ("testserver", 80),
        "scheme": "http",
        "query_string": b"",
    }
    return Request(scope)


class TestGetClientIp:
    def test_uses_x_forwarded_for_from_trusted_proxy(self):
        req = _request(
            peer="172.18.0.2",
            headers=[(b"x-forwarded-for", b"203.0.113.10, 172.18.0.2")],
        )
        assert get_client_ip(req) == "203.0.113.10"

    def test_ignores_spoofed_xff_from_untrusted_peer(self):
        req = _request(
            peer="203.0.113.99",
            headers=[(b"x-forwarded-for", b"1.2.3.4")],
        )
        assert get_client_ip(req) == "203.0.113.99"

    def test_falls_back_to_peer_when_trusted_proxy_has_no_headers(self):
        req = _request(peer="10.0.0.5")
        assert get_client_ip(req) == "10.0.0.5"

    def test_uses_x_real_ip_from_trusted_proxy(self):
        req = _request(
            peer="192.168.1.1",
            headers=[(b"x-real-ip", b"91.79.1.251")],
        )
        assert get_client_ip(req) == "91.79.1.251"
