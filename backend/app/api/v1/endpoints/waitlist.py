"""Public waitlist. Does not return the address or the confirmation token."""
from __future__ import annotations

from fastapi import APIRouter

from app.services.waitlist.service import (
    confirm,
    join,
    public_status,
    request_preorder,
    unsubscribe,
)

router = APIRouter(prefix="/waitlist", tags=["waitlist"])


def _public(row: dict) -> dict:
    hidden = {"token", "email", "name"}
    return {key: value for key, value in row.items() if key not in hidden}


@router.get("/offer")
def get_waitlist_offer() -> dict:
    return public_status()


@router.post("/join")
def post_waitlist_join(
    email: str,
    broker: str,
    portfolio_range: str,
    consent: bool = False,
    name: str = "",
    honeypot: str = "",
) -> dict:
    return _public(join(email=email, name=name or None, broker=broker, portfolio_range=portfolio_range, consent=consent, honeypot=honeypot))


@router.post("/confirm")
def post_waitlist_confirm(token: str) -> dict:
    return confirm(token)


@router.post("/unsubscribe")
def post_waitlist_unsubscribe(token: str) -> dict:
    return unsubscribe(token)


@router.post("/preorder")
def post_waitlist_preorder(token: str, plan: str = "personal") -> dict:
    return request_preorder(plan=plan, token=token)
