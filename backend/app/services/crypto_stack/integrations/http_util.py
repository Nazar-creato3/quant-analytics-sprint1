"""Shared HTTP probe / proxy helpers for sidecar integrations."""
from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

import httpx


def probe_url(url: str, *, timeout: float = 3.0) -> dict[str, Any]:
    """GET a sidecar URL; never raises."""
    try:
        # Sidecars are loopback/host-gateway — never route via HTTPS_PROXY.
        with httpx.Client(timeout=timeout, follow_redirects=True, trust_env=False) as client:
            resp = client.get(url)
        return {
            "reachable": True,
            "status_code": resp.status_code,
            "url": url,
            "ok": resp.is_success,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "reachable": False,
            "status_code": None,
            "url": url,
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


def proxy_get(base_url: str, path: str, *, timeout: float = 10.0) -> dict[str, Any]:
    """Forward GET to sidecar; returns structured result (not raw Response)."""
    base = base_url if base_url.endswith("/") else base_url + "/"
    clean = path.lstrip("/")
    url = urljoin(base, clean)
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True, trust_env=False) as client:
            resp = client.get(url)
        content_type = resp.headers.get("content-type", "")
        body: Any
        if "application/json" in content_type:
            try:
                body = resp.json()
            except Exception:  # noqa: BLE001
                body = resp.text[:4000]
        else:
            body = resp.text[:4000]
        return {
            "ok": resp.is_success,
            "status_code": resp.status_code,
            "url": url,
            "body": body,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "status_code": None,
            "url": url,
            "error": f"{type(exc).__name__}: {exc}",
        }
