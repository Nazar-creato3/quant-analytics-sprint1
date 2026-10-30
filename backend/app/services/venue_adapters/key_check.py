"""Reject keys with withdraw/transfer (Prompt 06 / R7). Never log secrets."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.logging import get_logger
from app.services.venue_adapters.errors import WithdrawKeyRejected

logger = get_logger(__name__)

_WITHDRAW_FLAGS = {
    "withdraw",
    "withdrawal",
    "enablewithdrawals",
    "transfer",
    "internaltransfer",
    "canwithdraw",
    "funds",
}


@dataclass(frozen=True)
class KeyInspection:
    venue: str
    ok: bool
    readonly: bool
    can_trade: bool
    withdraw: bool
    transfer: bool
    scopes: tuple[str, ...]
    user_confirmed_no_withdraw: bool = False


def inspect_key_permissions(
    venue: str,
    scopes: list[str] | tuple[str, ...],
    *,
    user_confirmed_no_withdraw: bool = False,
    programmable: bool = True,
) -> KeyInspection:
    normalized = tuple(str(s).strip().lower() for s in scopes if str(s).strip())
    withdraw = any(any(flag in s for flag in _WITHDRAW_FLAGS) for s in normalized)
    transfer = any("transfer" in s for s in normalized)
    readonly = any(s in {"read", "readonly", "read_only"} for s in normalized) and not any(
        s in {"trade", "orders"} for s in normalized
    )
    can_trade = any(s in {"trade", "orders", "brokerage"} for s in normalized)
    if withdraw or transfer:
        logger.info("venue key rejected", venue=venue, reason="withdraw_or_transfer")
        raise WithdrawKeyRejected(venue)
    if not programmable:
        if not user_confirmed_no_withdraw:
            raise WithdrawKeyRejected(venue)
        logger.info("venue key accepted with user confirmation", venue=venue)
    return KeyInspection(
        venue=venue,
        ok=True,
        readonly=readonly,
        can_trade=can_trade and not readonly,
        withdraw=False,
        transfer=False,
        scopes=normalized,
        user_confirmed_no_withdraw=user_confirmed_no_withdraw,
    )


def redact_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "***"
    return value[:2] + "***" + value[-2:]


def assert_not_logged(payload: Any, secret: str) -> None:
    text = str(payload)
    if secret and secret in text:
        raise AssertionError("secret leaked into log payload")
