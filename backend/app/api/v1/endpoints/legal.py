"""Public legal documents from legal/<code>/<version>.md."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from app.services.legal.catalog import INTERNAL_CODES, get_document, list_documents, load_ui_texts, validate_catalog
from app.services.legal.gates import (
    CLOSED_REASON,
    demo_contour,
    draft_badge_on,
    payment_open,
    registration_open,
    waitlist_open,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/legal", tags=["legal"])

_NOT_FOUND_RU = "Документ не найден"


def _public(row: dict) -> dict:
    return {
        "code": row["code"],
        "version": row["version"],
        "effective_date": row["effective_date"],
        "status": row["status"],
        "approved_by": row["approved_by"],
        # What the reader sees: operator details filled, chosen variants only.
        # sha256 above still identifies the stored source text.
        "body": row.get("rendered") or row["body"],
        "sha256": row["sha256"],
        "draft_badge": draft_badge_on() and row["status"] == "draft",
    }


@router.get("/status")
def legal_status() -> dict:
    errors = validate_catalog()
    if errors:
        logger.warning("legal_catalog_errors count=%s", len(errors))
    return {
        "catalog_ok": errors == [],
        "demo": demo_contour(),
        "draft_badge": draft_badge_on(),
        "registration_open": registration_open(),
        "waitlist_open": waitlist_open(),
        "payment_open": payment_open(),
        "closed_reason": None if registration_open() and waitlist_open() and payment_open() else CLOSED_REASON,
    }


@router.get("/ui-texts")
def legal_ui_texts() -> dict:
    return load_ui_texts()


@router.get("/{code}")
def legal_latest(code: str) -> dict:
    row = None if code in INTERNAL_CODES else get_document(code)
    if row is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND_RU)
    return _public(row)


@router.get("/{code}/{version}")
def legal_version(code: str, version: str) -> dict:
    row = None if code in INTERNAL_CODES else get_document(code, version)
    if row is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND_RU)
    return _public(row)


@router.get("/")
def legal_index() -> dict:
    rows = list_documents()
    return {"documents": [_public(row) for row in rows if row["code"] not in INTERNAL_CODES]}
