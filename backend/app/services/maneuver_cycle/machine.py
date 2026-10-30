"""State machine for the maneuver approval cycle (Prompt 39).

Methodology: docs/methodology/maneuver-cycle.md
"""
from __future__ import annotations

STATES = (
    "proposed",
    "viewed",
    "edited",
    "approved",
    "rejected",
    "expired",
    "sent",
    "executed_partial",
    "executed_full",
    "closed",
)

# Paper fills before this prompt used executed_paper. It is not a live state.
LEGACY_PAPER_FILL = "executed_paper"

ALLOWED: dict[str, frozenset[str]] = {
    "proposed": frozenset({"viewed", "rejected", "expired"}),
    "viewed": frozenset({"edited", "approved", "rejected", "expired"}),
    "edited": frozenset({"edited", "approved", "rejected", "expired"}),
    "approved": frozenset({"sent", "expired"}),
    "rejected": frozenset(),
    "expired": frozenset(),
    "sent": frozenset({"executed_partial", "executed_full"}),
    "executed_partial": frozenset({"executed_full", "closed"}),
    "executed_full": frozenset({"closed"}),
    LEGACY_PAPER_FILL: frozenset({"closed"}),
    "closed": frozenset(),
}

STATUS_LABELS_RU = {
    "proposed": "предложен",
    "viewed": "просмотрен",
    "edited": "отредактирован",
    "approved": "одобрен",
    "rejected": "отклонён",
    "expired": "истёк",
    "sent": "отправлен",
    "executed_partial": "исполнен частично",
    "executed_full": "исполнен полностью",
    "executed_paper": "исполнен на бумаге",
    "closed": "закрыт",
}

REJECT_REASONS = {
    "not_needed": "не требуется",
    "size": "размер",
    "timing": "срок",
    "other": "другое",
}


class TransitionError(ValueError):
    """Illegal status change. Subclass of ValueError so the API maps it to 400."""


def allowed_targets(status: str) -> frozenset[str]:
    if status not in ALLOWED:
        return frozenset()
    return ALLOWED[status]


def assert_transition(current: str, nxt: str) -> None:
    if nxt not in allowed_targets(current):
        raise TransitionError(f"переход {current} → {nxt} запрещён")
