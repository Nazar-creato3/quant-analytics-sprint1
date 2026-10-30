"""Transactional email pipeline and account recovery tables."""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0036_email_account_recovery"
down_revision: Union[str, None] = "0035_application_twenty_crm"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE users
            ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMPTZ NULL;

        CREATE TABLE IF NOT EXISTS email_jobs (
            id VARCHAR(36) PRIMARY KEY,
            job_type VARCHAR(64) NOT NULL,
            template VARCHAR(128) NOT NULL,
            to_email VARCHAR(255) NOT NULL,
            payload JSONB NOT NULL DEFAULT '{}',
            status VARCHAR(32) NOT NULL DEFAULT 'pending',
            idempotency_key VARCHAR(128) NOT NULL UNIQUE,
            attempts INTEGER NOT NULL DEFAULT 0,
            provider VARCHAR(32) NULL,
            provider_message_id VARCHAR(128) NULL,
            last_error TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            sent_at TIMESTAMPTZ NULL
        );
        CREATE INDEX IF NOT EXISTS ix_email_jobs_job_type ON email_jobs(job_type);
        CREATE INDEX IF NOT EXISTS ix_email_jobs_to_email ON email_jobs(to_email);
        CREATE INDEX IF NOT EXISTS ix_email_jobs_status ON email_jobs(status);

        CREATE TABLE IF NOT EXISTS email_events (
            id VARCHAR(36) PRIMARY KEY,
            job_id VARCHAR(36) NULL REFERENCES email_jobs(id) ON DELETE SET NULL,
            provider_message_id VARCHAR(128) NULL,
            event_type VARCHAR(32) NOT NULL,
            occurred_at TIMESTAMPTZ NOT NULL,
            raw_payload JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS ix_email_events_job_id ON email_events(job_id);
        CREATE INDEX IF NOT EXISTS ix_email_events_provider_message_id ON email_events(provider_message_id);
        CREATE INDEX IF NOT EXISTS ix_email_events_event_type ON email_events(event_type);

        CREATE TABLE IF NOT EXISTS suppressed_emails (
            email VARCHAR(255) PRIMARY KEY,
            reason VARCHAR(64) NOT NULL,
            suppressed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            cleared_at TIMESTAMPTZ NULL
        );

        CREATE TABLE IF NOT EXISTS recovery_tokens (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_hash VARCHAR(64) NOT NULL UNIQUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at TIMESTAMPTZ NOT NULL,
            used_at TIMESTAMPTZ NULL
        );
        CREATE INDEX IF NOT EXISTS ix_recovery_tokens_user_id ON recovery_tokens(user_id);
        CREATE INDEX IF NOT EXISTS ix_recovery_tokens_token_hash ON recovery_tokens(token_hash);
        CREATE INDEX IF NOT EXISTS ix_recovery_tokens_user_active ON recovery_tokens(user_id, used_at);

        CREATE TABLE IF NOT EXISTS verification_tokens (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_hash VARCHAR(64) NOT NULL UNIQUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at TIMESTAMPTZ NOT NULL,
            used_at TIMESTAMPTZ NULL
        );
        CREATE INDEX IF NOT EXISTS ix_verification_tokens_user_id ON verification_tokens(user_id);
        CREATE INDEX IF NOT EXISTS ix_verification_tokens_token_hash ON verification_tokens(token_hash);
        CREATE INDEX IF NOT EXISTS ix_verification_tokens_user_active ON verification_tokens(user_id, used_at);

        CREATE TABLE IF NOT EXISTS security_audit_log (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) NULL REFERENCES users(id) ON DELETE SET NULL,
            event_type VARCHAR(64) NOT NULL,
            ip VARCHAR(45) NULL,
            user_agent VARCHAR(512) NULL,
            details JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS ix_security_audit_log_user_id ON security_audit_log(user_id);
        CREATE INDEX IF NOT EXISTS ix_security_audit_log_event_type ON security_audit_log(event_type);
        CREATE INDEX IF NOT EXISTS ix_security_audit_log_created_at ON security_audit_log(created_at);

        CREATE TABLE IF NOT EXISTS email_templates (
            id VARCHAR(36) PRIMARY KEY,
            name VARCHAR(128) NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            subject VARCHAR(255) NOT NULL,
            html_body TEXT NOT NULL,
            text_body TEXT NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_email_templates_name_version UNIQUE (name, version)
        );
        CREATE INDEX IF NOT EXISTS ix_email_templates_name ON email_templates(name);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS email_templates;
        DROP TABLE IF EXISTS security_audit_log;
        DROP TABLE IF EXISTS verification_tokens;
        DROP TABLE IF EXISTS recovery_tokens;
        DROP TABLE IF EXISTS suppressed_emails;
        DROP TABLE IF EXISTS email_events;
        DROP TABLE IF EXISTS email_jobs;
        ALTER TABLE users DROP COLUMN IF EXISTS email_verified_at;
        """
    )
