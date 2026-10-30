"""Execution gate — broker orders must flow through DealIntent → Approval → Execution."""
from __future__ import annotations

from dataclasses import dataclass

from app.domain.deal_intent_enums import DealIntentStatus


class DirectOrderBypassError(RuntimeError):
    """Raised when code attempts broker/exchange submission without an executing DealIntent."""

    def __init__(self, message: str | None = None):
        default = (
            "Direct broker order submission is forbidden. "
            "All execution must flow through DealIntent → Approval → Execution."
        )
        super().__init__(message or default)


@dataclass(frozen=True)
class DealIntentExecutionContext:
    """Execution authorization tied to an approved DealIntent in EXECUTING state."""

    deal_intent_id: str
    status: DealIntentStatus


@dataclass(frozen=True)
class ManeuverExecutionContext:
    """Execution authorization for approved paper maneuvers."""

    maneuver_id: str
    status: str


@dataclass(frozen=True)
class ManualOrderExecutionContext:
    """Operator-initiated manual ticket (Direct Deals) — paper fills allowed."""

    manual_order_id: str


class ExecutionGate:
    """Validates that broker submission is authorized by DealIntent lifecycle."""

    _MANEUVER_ALLOWED = frozenset({"approved", "executing"})

    @staticmethod
    def require_executing_intent(
        context: DealIntentExecutionContext | None,
        *,
        maneuver_context: ManeuverExecutionContext | None = None,
        manual_order_context: ManualOrderExecutionContext | None = None,
    ) -> None:
        if manual_order_context is not None and manual_order_context.manual_order_id:
            return
        if maneuver_context is not None:
            if maneuver_context.maneuver_id and maneuver_context.status in ExecutionGate._MANEUVER_ALLOWED:
                return
            raise DirectOrderBypassError(
                f"Maneuver {maneuver_context.maneuver_id} must be approved or executing "
                f"(current: {maneuver_context.status})"
            )
        if context is None:
            raise DirectOrderBypassError()
        if not context.deal_intent_id:
            raise DirectOrderBypassError("deal_intent_id is required for broker submission")
        if context.status != DealIntentStatus.EXECUTING:
            raise DirectOrderBypassError(
                f"DealIntent {context.deal_intent_id} must be in 'executing' status "
                f"(current: {context.status.value})"
            )

    @staticmethod
    def context_from_status(deal_intent_id: str | None, status: DealIntentStatus | None) -> DealIntentExecutionContext:
        if not deal_intent_id or status is None:
            raise DirectOrderBypassError()
        return DealIntentExecutionContext(deal_intent_id=deal_intent_id, status=status)
