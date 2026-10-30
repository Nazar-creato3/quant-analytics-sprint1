"""Unit tests for DealIntent state machine — all valid and invalid transitions."""
from __future__ import annotations

import pytest

from app.domain.deal_intent_enums import DealIntentStatus, TERMINAL_DEAL_INTENT_STATUSES
from app.domain.deal_intent_fsm import (
    DEAL_INTENT_TRANSITIONS,
    DealIntentEvent,
    DealIntentLifecycle,
    DealIntentStateMachine,
    DealIntentTransitionError,
)


@pytest.fixture
def machine() -> DealIntentStateMachine:
    return DealIntentStateMachine()


class TestValidTransitions:
    @pytest.mark.parametrize(
        "from_status,event,to_status",
        [
            (DealIntentStatus.DRAFT, DealIntentEvent.SUBMIT, DealIntentStatus.PENDING_APPROVAL),
            (DealIntentStatus.DRAFT, DealIntentEvent.CANCEL, DealIntentStatus.CANCELLED),
            (DealIntentStatus.PENDING_APPROVAL, DealIntentEvent.APPROVE, DealIntentStatus.APPROVED),
            (DealIntentStatus.PENDING_APPROVAL, DealIntentEvent.REJECT, DealIntentStatus.REJECTED),
            (DealIntentStatus.PENDING_APPROVAL, DealIntentEvent.HOLD, DealIntentStatus.HELD),
            (DealIntentStatus.PENDING_APPROVAL, DealIntentEvent.CANCEL, DealIntentStatus.CANCELLED),
            (DealIntentStatus.HELD, DealIntentEvent.APPROVE, DealIntentStatus.APPROVED),
            (DealIntentStatus.HELD, DealIntentEvent.REJECT, DealIntentStatus.REJECTED),
            (DealIntentStatus.HELD, DealIntentEvent.RELEASE, DealIntentStatus.PENDING_APPROVAL),
            (DealIntentStatus.HELD, DealIntentEvent.CANCEL, DealIntentStatus.CANCELLED),
            (DealIntentStatus.APPROVED, DealIntentEvent.EXECUTE, DealIntentStatus.EXECUTING),
            (DealIntentStatus.APPROVED, DealIntentEvent.HOLD, DealIntentStatus.HELD),
            (DealIntentStatus.APPROVED, DealIntentEvent.CANCEL, DealIntentStatus.CANCELLED),
            (DealIntentStatus.EXECUTING, DealIntentEvent.FILL, DealIntentStatus.FILLED),
            (DealIntentStatus.EXECUTING, DealIntentEvent.FAIL, DealIntentStatus.FAILED),
            (DealIntentStatus.EXECUTING, DealIntentEvent.CANCEL, DealIntentStatus.CANCELLED),
        ],
    )
    def test_valid_transition(
        self,
        machine: DealIntentStateMachine,
        from_status: DealIntentStatus,
        event: DealIntentEvent,
        to_status: DealIntentStatus,
    ):
        assert machine.can_transition(from_status, event)
        assert machine.next_status(from_status, event) == to_status

    def test_happy_path_lifecycle(self, machine: DealIntentStateMachine):
        lifecycle = DealIntentLifecycle(deal_intent_id="intent-1")
        path = [
            (DealIntentEvent.SUBMIT, DealIntentStatus.PENDING_APPROVAL),
            (DealIntentEvent.APPROVE, DealIntentStatus.APPROVED),
            (DealIntentEvent.EXECUTE, DealIntentStatus.EXECUTING),
            (DealIntentEvent.FILL, DealIntentStatus.FILLED),
        ]
        for event, expected in path:
            machine.apply(lifecycle, event, reason=event.value)
            assert lifecycle.status == expected
        assert len(lifecycle.history) == 4
        assert machine.is_terminal(lifecycle.status)

    def test_hold_and_release_path(self, machine: DealIntentStateMachine):
        lifecycle = DealIntentLifecycle(deal_intent_id="intent-2")
        machine.apply(lifecycle, DealIntentEvent.SUBMIT)
        machine.apply(lifecycle, DealIntentEvent.HOLD, reason="manual review")
        assert lifecycle.status == DealIntentStatus.HELD
        machine.apply(lifecycle, DealIntentEvent.RELEASE)
        assert lifecycle.status == DealIntentStatus.PENDING_APPROVAL
        machine.apply(lifecycle, DealIntentEvent.APPROVE)
        machine.apply(lifecycle, DealIntentEvent.EXECUTE)
        machine.apply(lifecycle, DealIntentEvent.FAIL, reason="broker reject")
        assert lifecycle.status == DealIntentStatus.FAILED


class TestInvalidTransitions:
    @pytest.mark.parametrize("terminal_status", sorted(TERMINAL_DEAL_INTENT_STATUSES, key=lambda s: s.value))
    @pytest.mark.parametrize("event", list(DealIntentEvent))
    def test_terminal_states_reject_all_events(
        self,
        machine: DealIntentStateMachine,
        terminal_status: DealIntentStatus,
        event: DealIntentEvent,
    ):
        with pytest.raises(DealIntentTransitionError) as exc_info:
            machine.next_status(terminal_status, event)
        assert exc_info.value.from_status == terminal_status
        assert exc_info.value.event == event.value

    @pytest.mark.parametrize(
        "from_status,event",
        [
            (DealIntentStatus.DRAFT, DealIntentEvent.APPROVE),
            (DealIntentStatus.DRAFT, DealIntentEvent.EXECUTE),
            (DealIntentStatus.DRAFT, DealIntentEvent.FILL),
            (DealIntentStatus.PENDING_APPROVAL, DealIntentEvent.SUBMIT),
            (DealIntentStatus.PENDING_APPROVAL, DealIntentEvent.EXECUTE),
            (DealIntentStatus.PENDING_APPROVAL, DealIntentEvent.FILL),
            (DealIntentStatus.HELD, DealIntentEvent.SUBMIT),
            (DealIntentStatus.HELD, DealIntentEvent.EXECUTE),
            (DealIntentStatus.APPROVED, DealIntentEvent.SUBMIT),
            (DealIntentStatus.APPROVED, DealIntentEvent.FILL),
            (DealIntentStatus.APPROVED, DealIntentEvent.REJECT),
            (DealIntentStatus.EXECUTING, DealIntentEvent.APPROVE),
            (DealIntentStatus.EXECUTING, DealIntentEvent.SUBMIT),
            (DealIntentStatus.EXECUTING, DealIntentEvent.HOLD),
        ],
    )
    def test_invalid_transition_raises(
        self,
        machine: DealIntentStateMachine,
        from_status: DealIntentStatus,
        event: DealIntentEvent,
    ):
        assert not machine.can_transition(from_status, event)
        with pytest.raises(DealIntentTransitionError) as exc_info:
            machine.apply_to_status(from_status, event)
        assert exc_info.value.from_status == from_status
        assert exc_info.value.event == event.value

    def test_apply_on_lifecycle_preserves_status_on_error(self, machine: DealIntentStateMachine):
        lifecycle = DealIntentLifecycle(deal_intent_id="intent-3", status=DealIntentStatus.DRAFT)
        with pytest.raises(DealIntentTransitionError):
            machine.apply(lifecycle, DealIntentEvent.FILL)
        assert lifecycle.status == DealIntentStatus.DRAFT
        assert lifecycle.history == []


class TestTransitionCoverage:
    def test_all_non_terminal_states_have_transitions(self):
        non_terminal = {s for s in DealIntentStatus if s not in TERMINAL_DEAL_INTENT_STATUSES}
        assert set(DEAL_INTENT_TRANSITIONS.keys()) == non_terminal

    def test_every_declared_transition_is_valid(self, machine: DealIntentStateMachine):
        for from_status, events in DEAL_INTENT_TRANSITIONS.items():
            for event, to_status in events.items():
                assert machine.next_status(from_status, event) == to_status

    @pytest.mark.parametrize("from_status", list(DealIntentStatus))
    @pytest.mark.parametrize("event", list(DealIntentEvent))
    def test_complete_transition_matrix(
        self,
        machine: DealIntentStateMachine,
        from_status: DealIntentStatus,
        event: DealIntentEvent,
    ):
        expected_allowed = event in DEAL_INTENT_TRANSITIONS.get(from_status, {})
        assert machine.can_transition(from_status, event) == expected_allowed
        if expected_allowed:
            machine.next_status(from_status, event)
        else:
            with pytest.raises(DealIntentTransitionError):
                machine.next_status(from_status, event)
