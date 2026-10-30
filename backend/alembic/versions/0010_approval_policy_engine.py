"""Add review_queue for ApprovalPolicyEngine manual review workflow.

Revision ID: 0010_approval_policy_engine
Revises: 0009_deal_intent
Create Date: 2026-07-18
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0010_approval_policy_engine"
down_revision: Union[str, None] = "0009_deal_intent"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS review_queue (
            id               VARCHAR(36) PRIMARY KEY,
            profile_id       VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            sleeve_id        VARCHAR(36) NOT NULL REFERENCES sleeves(id) ON DELETE CASCADE,
            deal_intent_id   VARCHAR(36) NOT NULL REFERENCES deal_intents(id) ON DELETE CASCADE,
            policy_state     VARCHAR(30) NOT NULL DEFAULT 'hold_for_review',
            reason           TEXT NOT NULL,
            risk_score       DOUBLE PRECISION NOT NULL
                CHECK (risk_score >= 0 AND risk_score <= 1),
            intent_snapshot  JSONB NOT NULL DEFAULT '{}'::jsonb,
            status           VARCHAR(20) NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'resolved', 'cancelled')),
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            resolved_at      TIMESTAMPTZ
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_review_queue_profile_id ON review_queue (profile_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_review_queue_sleeve_id ON review_queue (sleeve_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_review_queue_deal_intent_id ON review_queue (deal_intent_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_review_queue_status_created "
        "ON review_queue (status, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS review_queue")
