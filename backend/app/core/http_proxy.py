"""Selective HTTP proxy policy for RU VPS.

Foreign market APIs (Alpaca, Polygon, …) may need FOREIGN_HTTPS_PROXY.
Russian / RU-reachable hosts (MOEX, Binance, CBR, *.ru) must stay direct.

Never log proxy credentials — callers only receive a URL (or None).
"""
from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

# Hosts that must never be forced through the Frankfurt / foreign proxy.
DIRECT_HOST_SUFFIXES: tuple[str, ...] = (
    "localhost",
    "127.0.0.1",
    "postgres",
    "redis",
    "backend",
    ".moex.com",
    "iss.moex.com",
    "api.binance.com",
    "data-api.binance.vision",
    "stream.binance.com",
    "fapi.binance.com",
    "dapi.binance.com",
    "cbr.ru",
    "www.cbr.ru",
    ".cbr.ru",
    "interfax.ru",
    ".interfax.ru",
    "rbc.ru",
    ".rbc.ru",
    "aitunnel.ru",
    ".aitunnel.ru",
    "unisender.ru",
    ".unisender.ru",
    ".ru",
)

DEFAULT_NO_PROXY = (
    "localhost,127.0.0.1,postgres,redis,backend,mlflow,flower,"
    "*.moex.com,iss.moex.com,"
    "api.binance.com,data-api.binance.vision,stream.binance.com,"
    "*.binance.com,*.cbr.ru,cbr.ru,"
    "*.interfax.ru,*.rbc.ru,*.ru"
)


def _settings_proxy() -> str:
    try:
        from app.core.config import get_settings

        s = get_settings()
        for attr in ("FOREIGN_HTTPS_PROXY", "HTTPS_PROXY", "HTTP_PROXY"):
            val = getattr(s, attr, None)
            if isinstance(val, str) and val.strip():
                return val.strip()
    except Exception:
        pass
    for key in ("FOREIGN_HTTPS_PROXY", "HTTPS_PROXY", "HTTP_PROXY"):
        val = (os.getenv(key) or "").strip()
        if val:
            return val
    return ""


def foreign_https_proxy() -> str | None:
    """Return proxy URL for foreign APIs, or None if unset."""
    return _settings_proxy() or None


def proxy_is_configured() -> bool:
    return foreign_https_proxy() is not None


def host_must_be_direct(host: str | None) -> bool:
    if not host:
        return True
    h = host.strip().lower().rstrip(".")
    if not h:
        return True
    for suffix in DIRECT_HOST_SUFFIXES:
        if suffix.startswith("."):
            if h.endswith(suffix) or h == suffix[1:]:
                return True
        elif h == suffix or h.endswith("." + suffix):
            return True
    return False


def url_must_be_direct(url: str) -> bool:
    try:
        return host_must_be_direct(urlparse(url).hostname)
    except Exception:
        return True




def httpx_ssl_verify() -> bool | str:
    """CA bundle for httpx — certifi by default; env overrides for corporate MITM."""
    for key in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"):
        val = (os.getenv(key) or "").strip()
        if val:
            return val
    try:
        import certifi

        return certifi.where()
    except Exception:
        return True


def httpx_client_kwargs(*, foreign: bool, timeout: Any = None) -> dict[str, Any]:
    """
    Build httpx.AsyncClient/Client kwargs.

    foreign=True  → use FOREIGN_HTTPS_PROXY when set; never fall back to blind env.
    foreign=False → explicit direct (proxy=None, trust_env=False) so global HTTPS_PROXY
                    cannot hijack MOEX/Binance.
    """
    kwargs: dict[str, Any] = {"trust_env": False}
    if timeout is not None:
        kwargs["timeout"] = timeout
    kwargs["verify"] = httpx_ssl_verify()
    if foreign:
        proxy = foreign_https_proxy()
        if proxy:
            kwargs["proxy"] = proxy
    else:
        kwargs["proxy"] = None
    return kwargs


def apply_direct_requests_session(session: Any) -> Any:
    """Force a requests.Session to bypass env proxies (MOEX / RU)."""
    session.trust_env = False
    try:
        session.proxies.clear()
    except Exception:
        session.proxies = {"http": None, "https": None}
    return session


def redacted_proxy_status() -> dict[str, Any]:
    """Safe status for data-health — never include credentials."""
    raw = foreign_https_proxy()
    if not raw:
        return {"foreign_proxy": "unset", "scheme": None, "host": None, "port": None}
    try:
        parsed = urlparse(raw)
        host = parsed.hostname
        port = parsed.port
        scheme = parsed.scheme or "http"
    except Exception:
        host, port, scheme = None, None, None
    return {
        "foreign_proxy": "set",
        "scheme": scheme,
        "host": host,
        "port": port,
    }


def configure_yfinance_proxy() -> bool:
    """Send yfinance (Yahoo) through FOREIGN_HTTPS_PROXY. Yahoo is closed for Russian IPs.

    Process-wide and idempotent; MOEX/RU clients build their own sessions and stay direct.
    """
    proxy = foreign_https_proxy()
    if not proxy:
        return False
    try:
        import yfinance as yf

        net = getattr(getattr(yf, "config", None), "network", None)
        if net is not None and hasattr(net, "proxy"):
            net.proxy = proxy  # yfinance >= 1.6
        else:
            yf.set_config(proxy=proxy)
        return True
    except Exception:
        return False
