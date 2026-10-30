"""Redact API keys and secrets from error strings before logging or API responses."""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

_SENSITIVE_QUERY_KEYS = frozenset(
    {
        "apikey",
        "api_key",
        "token",
        "access_token",
        "access_key",
        "secret",
        "password",
        "x-rapidapi-key",
        "key",
        "auth",
        "authorization",
    }
)

# Bearer / Tiingo "Token <key>" / generic Authorization headers that may appear in errors.
_AUTH_SCHEME_RE = re.compile(
    r"((?:Bearer|Token|Basic)\s+)[A-Za-z0-9._\-+/=]{6,}",
    re.IGNORECASE,
)
_AUTH_HEADER_RE = re.compile(
    r"(Authorization\s*[:=]\s*)(['\"]?)[^\s'\"]{6,}\2",
    re.IGNORECASE,
)
_QUERY_SECRET_RE = re.compile(
    r"([?&](?:apikey|api_key|apiKey|token|access_token|access_key|secret|key|auth)=)[^&\s'\"]+",
    re.IGNORECASE,
)
# Header-style API keys sometimes dumped into exception text (CoinGecko / RapidAPI).
_HEADER_KEY_RE = re.compile(
    r"((?:x-cg-(?:demo|pro)-api-key|x-rapidapi-key|x-api-key)\s*[:=]\s*)(['\"]?)[^\s'\"]{6,}\2",
    re.IGNORECASE,
)


def redact_secrets(text: Optional[str]) -> Optional[str]:
    """Mask secrets embedded in URLs, auth schemes, or API-key headers."""
    if not text:
        return text
    out = _AUTH_SCHEME_RE.sub(r"\1***", text)
    out = _AUTH_HEADER_RE.sub(r"\1\2***\2", out)
    out = _HEADER_KEY_RE.sub(r"\1\2***\2", out)
    out = _QUERY_SECRET_RE.sub(r"\1***", out)
    for match in re.finditer(r"https?://[^\s'\"]+", out):
        sanitized = _sanitize_url(match.group(0))
        if sanitized != match.group(0):
            out = out.replace(match.group(0), sanitized)
    return out


def _sanitize_url(url: str) -> str:
    try:
        parsed = urlparse(url)
    except Exception:
        return url
    if not parsed.query:
        return url
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    changed = False
    sanitized_pairs: list[tuple[str, str]] = []
    for key, value in pairs:
        if key.lower() in _SENSITIVE_QUERY_KEYS and value:
            sanitized_pairs.append((key, "***"))
            changed = True
        else:
            sanitized_pairs.append((key, value))
    if not changed:
        return url
    return urlunparse(parsed._replace(query=urlencode(sanitized_pairs)))
