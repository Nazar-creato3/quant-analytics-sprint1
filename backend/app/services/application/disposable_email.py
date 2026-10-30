"""Disposable email domain blocklist."""
from __future__ import annotations

# Common disposable domains — extend via DISPOSABLE_EMAIL_DOMAINS env (comma-separated).
_BUILTIN_DISPOSABLE = frozenset(
    {
        "mailinator.com",
        "guerrillamail.com",
        "tempmail.com",
        "throwaway.email",
        "yopmail.com",
        "10minutemail.com",
        "trashmail.com",
        "getnada.com",
        "sharklasers.com",
        "dispostable.com",
        "maildrop.cc",
        "temp-mail.org",
        "fakeinbox.com",
        "mailnesia.com",
    }
)


def is_disposable_email(email: str, extra_domains: frozenset[str] | None = None) -> bool:
    domain = email.strip().lower().split("@")[-1]
    blocked = _BUILTIN_DISPOSABLE
    if extra_domains:
        blocked = blocked | extra_domains
    return domain in blocked
