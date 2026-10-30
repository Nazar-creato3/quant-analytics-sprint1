"""Fail-closed registration, waitlist, and payment until approved texts + RKN notice."""
from __future__ import annotations

from app.core.config import settings
from app.services.legal.catalog import (
    CatalogError,
    document_approved,
    load_decisions,
    load_operator,
    rkn_notice_filed,
)

CLOSED_REASON = (
    "закрыто до утверждённых юридических текстов и уведомления Роскомнадзора"
)

REGISTRATION_CODES = ("terms", "privacy", "consent_pd")
WAITLIST_CODES = ("consent_waitlist", "privacy")
PAYMENT_CODES = ("subscription", "terms")


def demo_contour() -> bool:
    return bool(settings.QA_E2E_DEMO)


def _all_approved(codes: tuple[str, ...]) -> bool:
    try:
        return all(document_approved(code) for code in codes) and rkn_notice_filed()
    except CatalogError:
        return False


def receipts_enabled() -> bool:
    """Online cash register flag. Stays false until 54-FZ path is ready (D-149-4)."""
    try:
        payments = load_operator().get("payments") or {}
        return bool(payments.get("receipts_enabled")) is True
    except CatalogError:
        return False


def registration_open() -> bool:
    if demo_contour():
        return True
    return _all_approved(REGISTRATION_CODES)


def waitlist_open() -> bool:
    if demo_contour():
        return False
    return _all_approved(WAITLIST_CODES)


def payment_open() -> bool:
    # D-149-4: approved offer + RKN are not enough; receipts_enabled must be true.
    return _all_approved(PAYMENT_CODES) and receipts_enabled()


def draft_badge_on() -> bool:
    return demo_contour()


def decision(code: str, default: str = "A") -> str:
    """Lawyer's answer from legal/decisions.yaml ("A"/"B"); default when unreadable."""
    try:
        value = str(load_decisions().get(code) or default).strip().upper()
    except (CatalogError, OSError):
        return default
    # Accept the Cyrillic letters the founder may type ("L-03: Б").
    return {"А": "A", "Б": "B"}.get(value, value)


def real_orders_allowed() -> bool:
    """L-03: B — orders on maneuvers may reach a broker with real money (each confirmed)."""
    return decision("L-03") == "B"


def foreign_venues_live_allowed() -> bool:
    """L-04: A — foreign crypto venues may be used with real money (after RKN cross-border notice)."""
    return decision("L-04") == "A"


FOREIGN_LIVE_VENUES = frozenset({"binance", "bybit", "bitget", "mexc", "tokenized_equity"})
