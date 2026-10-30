"""Read-only public accuracy. Does not accept a posted number."""
from __future__ import annotations

from fastapi import APIRouter

from app.services.public_accuracy.service import public_accuracy, verify_journal

router = APIRouter(prefix="/public/accuracy", tags=["public-accuracy"])


@router.get("")
def get_public_accuracy() -> dict:
    return public_accuracy()


@router.get("/verify")
def get_public_accuracy_verify(digest: str) -> dict:
    return {"match": verify_journal(digest)}
