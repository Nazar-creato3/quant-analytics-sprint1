"""Legal document catalog, placeholder checks, and fail-closed product gates."""

from app.services.legal.catalog import (
    REQUIRED_CODES,
    LEGAL_ROOT,
    catalog_error,
    get_document,
    list_documents,
    load_decisions,
    load_operator,
    load_ui_texts,
    validate_catalog,
)
from app.services.legal.gates import (
    CLOSED_REASON,
    demo_contour,
    payment_open,
    registration_open,
    waitlist_open,
)

__all__ = [
    "REQUIRED_CODES",
    "LEGAL_ROOT",
    "CLOSED_REASON",
    "catalog_error",
    "demo_contour",
    "get_document",
    "list_documents",
    "load_decisions",
    "load_operator",
    "load_ui_texts",
    "payment_open",
    "registration_open",
    "validate_catalog",
    "waitlist_open",
]
