"""DealIntent status state machine — sole authority for lifecycle transitions."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from app.domain.deal_intent_enums import TERMINAL_DEAL_INTENT_STATUSES, DealIntentStatus
from app.utils.helpers import utcnow


class DealIntentTransitionError(ValueError):
    """Raised when a status transition is not allowed."""

    def __init__(self, from_status: DealIntentStatus, event: str, to_status: DealIntentStatus | None = None):
        self.from_status = from_status
        self.event = event
        self.to_status = to_status
        if to_status is None:
            super().__init__(f"invalid transition: {from_status.value} --[{event}]--> (not allowed)")
        else:
            super().__init__(
                f"invalid transition: {from_status.value} --[{event}]--> {to_status.value} (not allowed)"
            )


class DealIntentEvent(str, Enum):
    SUBMIT = "submit"
    APPROVE = "approve"
    REJECT = "reject"
    HOLD = "hold"
    RELEASE = "release"
    EXECUTE = "execute"
    FILL = "fill"
    FAIL = "fail"
    CANCEL = "cancel"


# Valid transitions: current_status -> {event: next_status}
DEAL_INTENT_TRANSITIONS: dict[DealIntentStatus, dict[DealIntentEvent, DealIntentStatus]] = {
    DealIntentStatus.DRAFT: {
        DealIntentEvent.SUBMIT: DealIntentStatus.PENDING_APPROVAL,
        DealIntentEvent.CANCEL: DealIntentStatus.CANCELLED,
    },
    DealIntentStatus.PENDING_APPROVAL: {
        DealIntentEvent.APPROVE: DealIntentStatus.APPROVED,
        DealIntentEvent.REJECT: DealIntentStatus.REJECTED,
        DealIntentEvent.HOLD: DealIntentStatus.HELD,
        DealIntentEvent.CANCEL: DealIntentStatus.CANCELLED,
    },
    DealIntentStatus.HELD: {
        DealIntentEvent.APPROVE: DealIntentStatus.APPROVED,
        DealIntentEvent.REJECT: DealIntentStatus.REJECTED,
        DealIntentEvent.RELEASE: DealIntentStatus.PENDING_APPROVAL,
        DealIntentEvent.CANCEL: DealIntentStatus.CANCELLED,
    },
    DealIntentStatus.APPROVED: {
        DealIntentEvent.EXECUTE: DealIntentStatus.EXECUTING,
        DealIntentEvent.HOLD: DealIntentStatus.HELD,
        DealIntentEvent.CANCEL: DealIntentStatus.CANCELLED,
    },
    DealIntentStatus.EXECUTING: {
        DealIntentEvent.FILL: DealIntentStatus.FILLED,
        DealIntentEvent.FAIL: DealIntentStatus.FAILED,
        DealIntentEvent.CANCEL: DealIntentStatus.CANCELLED,
    },
}


@dataclass
class DealIntentTransitionRecord:
    at: datetime
    from_status: DealIntentStatus
    to_status: DealIntentStatus
    event: DealIntentEvent
    reason: str


@dataclass
class DealIntentLifecycle:
    """In-memory lifecycle tracker for a DealIntent."""

    deal_intent_id: str
    status: DealIntentStatus = DealIntentStatus.DRAFT
    updated_at: datetime = field(default_factory=utcnow)
    history: list[DealIntentTransitionRecord] = field(default_factory=list)

    def record(self, event: DealIntentEvent, next_status: DealIntentStatus, reason: str = "") -> None:
        record = DealIntentTransitionRecord(
            at=utcnow(),
            from_status=self.status,
            to_status=next_status,
            event=event,
            reason=reason,
        )
        self.status = next_status
        self.updated_at = record.at
        self.history.append(record)


class DealIntentStateMachine:
    """Lightweight FSM enforcing DealIntent status transitions."""

    transitions = DEAL_INTENT_TRANSITIONS

    def can_transition(self, status: DealIntentStatus, event: DealIntentEvent) -> bool:
        return event in self.transitions.get(status, {})

    def next_status(self, status: DealIntentStatus, event: DealIntentEvent) -> DealIntentStatus:
        allowed = self.transitions.get(status, {})
        if event not in allowed:
            raise DealIntentTransitionError(status, event.value)
        return allowed[event]

    def apply(
        self,
        lifecycle: DealIntentLifecycle,
        event: DealIntentEvent,
        reason: str = "",
    ) -> DealIntentLifecycle:
        next_status = self.next_status(lifecycle.status, event)
        lifecycle.record(event, next_status, reason)
        return lifecycle

    def apply_to_status(
        self,
        status: DealIntentStatus,
        event: DealIntentEvent,
    ) -> DealIntentStatus:
        return self.next_status(status, event)

    @staticmethod
    def is_terminal(status: DealIntentStatus) -> bool:
        return status in TERMINAL_DEAL_INTENT_STATUSES
