"""Add compliance context fields to profiles for ComplianceAccessLayer.

Revision ID: 0012_compliance_access
Revises: 0011_control_fabric
Create Date: 2026-07-18
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0012_compliance_access"
down_revision: Union[str, None] = "0011_control_fabric"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE profiles
            ADD COLUMN IF NOT EXISTS jurisdiction VARCHAR(10) NOT NULL DEFAULT 'global',
            ADD COLUMN IF NOT EXISTS account_type VARCHAR(20) NOT NULL DEFAULT 'retail',
            ADD COLUMN IF NOT EXISTS broker_agreement_status VARCHAR(20) NOT NULL DEFAULT 'pending'
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS compliance_policy_registry (
            id              VARCHAR(36) PRIMARY KEY,
            jurisdiction    VARCHAR(10) NOT NULL,
            account_type    VARCHAR(20) NOT NULL,
            config          JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (jurisdiction, account_type)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_compliance_policy_registry_jurisdiction
            ON compliance_policy_registry (jurisdiction)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS compliance_policy_registry")
    op.execute(
        """
        ALTER TABLE profiles
            DROP COLUMN IF EXISTS broker_agreement_status,
            DROP COLUMN IF EXISTS account_type,
            DROP COLUMN IF EXISTS jurisdiction
        """
    )
