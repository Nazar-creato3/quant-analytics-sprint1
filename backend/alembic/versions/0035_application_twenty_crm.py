"""Twenty CRM sync fields on applications table."""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0035_application_twenty_crm"
down_revision: Union[str, None] = "0034_position_audit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE applications
            ADD COLUMN IF NOT EXISTS twenty_crm_id VARCHAR(36) NULL,
            ADD COLUMN IF NOT EXISTS twenty_company_id VARCHAR(36) NULL,
            ADD COLUMN IF NOT EXISTS crm_sync_status VARCHAR(30) NOT NULL DEFAULT 'pending',
            ADD COLUMN IF NOT EXISTS crm_last_sync_at TIMESTAMPTZ NULL;

        CREATE INDEX IF NOT EXISTS ix_applications_twenty_crm_id
            ON applications(twenty_crm_id)
            WHERE twenty_crm_id IS NOT NULL;

        CREATE INDEX IF NOT EXISTS ix_applications_crm_sync_status
            ON applications(crm_sync_status);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS ix_applications_crm_sync_status;
        DROP INDEX IF EXISTS ix_applications_twenty_crm_id;
        ALTER TABLE applications
            DROP COLUMN IF EXISTS crm_last_sync_at,
            DROP COLUMN IF EXISTS crm_sync_status,
            DROP COLUMN IF EXISTS twenty_company_id,
            DROP COLUMN IF EXISTS twenty_crm_id;
        """
    )
