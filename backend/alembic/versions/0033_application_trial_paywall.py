"""Secure application flow, WebAuthn credentials, subscription paywall state."""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0033_application_trial_paywall"
down_revision: Union[str, None] = "0032_portfolio_rls"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE EXTENSION IF NOT EXISTS pg_trgm;

        ALTER TABLE users
            ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT false,
            ADD COLUMN IF NOT EXISTS trial_started_at TIMESTAMPTZ NULL;

        CREATE TABLE IF NOT EXISTS applications (
            id VARCHAR(36) PRIMARY KEY,
            name VARCHAR(200) NULL,
            email VARCHAR(255) NOT NULL,
            phone VARCHAR(50) NOT NULL,
            phone_hash VARCHAR(64) NOT NULL,
            jurisdiction VARCHAR(20) NULL,
            capital_range VARCHAR(50) NULL,
            experience VARCHAR(50) NULL,
            strategy_interest VARCHAR(200) NULL,
            comments TEXT NULL,
            status VARCHAR(30) NOT NULL DEFAULT 'pending_phone_otp',
            email_verification_token VARCHAR(128) NULL,
            email_verified_at TIMESTAMPTZ NULL,
            phone_verified_at TIMESTAMPTZ NULL,
            duplicate_flag BOOLEAN NOT NULL DEFAULT false,
            duplicate_reason TEXT NULL,
            apply_ip VARCHAR(64) NULL,
            user_id VARCHAR(36) NULL REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS ix_applications_email ON applications(email);
        CREATE INDEX IF NOT EXISTS ix_applications_phone_hash ON applications(phone_hash);
        CREATE INDEX IF NOT EXISTS ix_applications_status ON applications(status);
        CREATE INDEX IF NOT EXISTS ix_applications_name_trgm ON applications USING gin (name gin_trgm_ops);

        CREATE TABLE IF NOT EXISTS webauthn_credentials (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            credential_id TEXT NOT NULL UNIQUE,
            public_key BYTEA NOT NULL,
            sign_count BIGINT NOT NULL DEFAULT 0,
            device_label VARCHAR(120) NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_used_at TIMESTAMPTZ NULL
        );
        CREATE INDEX IF NOT EXISTS ix_webauthn_user ON webauthn_credentials(user_id);

        CREATE TABLE IF NOT EXISTS user_subscription_states (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
            subscription_status VARCHAR(30) NOT NULL DEFAULT 'none',
            trial_start_at TIMESTAMPTZ NULL,
            paid_at TIMESTAMPTZ NULL,
            payment_external_ref VARCHAR(120) NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS ix_user_sub_status ON user_subscription_states(subscription_status);

        CREATE TABLE IF NOT EXISTS subscription_status_audit (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL,
            from_status VARCHAR(30) NULL,
            to_status VARCHAR(30) NOT NULL,
            reason TEXT NULL,
            actor_user_id VARCHAR(36) NULL,
            meta JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS ix_sub_audit_user ON subscription_status_audit(user_id);
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'appuser') THEN
            REVOKE UPDATE, DELETE ON subscription_status_audit FROM appuser;
          END IF;
        EXCEPTION WHEN OTHERS THEN
          NULL;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS subscription_status_audit CASCADE;
        DROP TABLE IF EXISTS user_subscription_states CASCADE;
        DROP TABLE IF EXISTS webauthn_credentials CASCADE;
        DROP TABLE IF EXISTS applications CASCADE;
        ALTER TABLE users DROP COLUMN IF EXISTS must_change_password;
        ALTER TABLE users DROP COLUMN IF EXISTS trial_started_at;
        """
    )
