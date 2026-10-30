"""Origination system tables: access policy, admissions, devices, RBAC, billing, sub-portfolios."""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0023_origination"
down_revision: Union[str, None] = "0022_macro_registry"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE profiles
        ADD COLUMN IF NOT EXISTS access_level VARCHAR(40) NOT NULL DEFAULT 'trial_read_only';
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS access_policy_states (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL UNIQUE,
            access_level VARCHAR(40) NOT NULL DEFAULT 'trial_read_only',
            trial_started_at TIMESTAMPTZ NULL,
            trial_expires_at TIMESTAMPTZ NULL,
            manual_review_required BOOLEAN NOT NULL DEFAULT false,
            identity_cluster_id VARCHAR(36) NULL,
            trust_level VARCHAR(20) NOT NULL DEFAULT 'standard',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS ix_access_policy_user ON access_policy_states(user_id);

        CREATE TABLE IF NOT EXISTS admission_cases (
            id VARCHAR(36) PRIMARY KEY,
            status VARCHAR(30) NOT NULL DEFAULT 'lead',
            source VARCHAR(100) NOT NULL DEFAULT 'manual',
            jurisdiction VARCHAR(20) NULL,
            capital_range VARCHAR(50) NULL,
            experience_level VARCHAR(50) NULL,
            strategy_interest VARCHAR(200) NULL,
            owner_user_id VARCHAR(36) NULL,
            contact_email VARCHAR(255) NOT NULL,
            contact_name VARCHAR(200) NULL,
            contact_phone VARCHAR(50) NULL,
            user_id VARCHAR(36) NULL REFERENCES users(id) ON DELETE SET NULL,
            notes TEXT NULL,
            extra JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS ix_admission_status ON admission_cases(status);
        CREATE INDEX IF NOT EXISTS ix_admission_email ON admission_cases(contact_email);

        CREATE TABLE IF NOT EXISTS admission_status_history (
            id VARCHAR(36) PRIMARY KEY,
            case_id VARCHAR(36) NOT NULL REFERENCES admission_cases(id) ON DELETE CASCADE,
            from_status VARCHAR(30) NULL,
            to_status VARCHAR(30) NOT NULL,
            actor_user_id VARCHAR(36) NULL,
            reason TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS ix_admission_hist_case ON admission_status_history(case_id);

        CREATE TABLE IF NOT EXISTS devices (
            id VARCHAR(36) PRIMARY KEY,
            fingerprint_hash VARCHAR(64) NOT NULL UNIQUE,
            user_agent TEXT NULL,
            last_ip VARCHAR(64) NULL,
            first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS identity_clusters (
            id VARCHAR(36) PRIMARY KEY,
            notes TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS identity_cluster_members (
            id VARCHAR(36) PRIMARY KEY,
            cluster_id VARCHAR(36) NOT NULL REFERENCES identity_clusters(id) ON DELETE CASCADE,
            member_type VARCHAR(30) NOT NULL,
            member_key VARCHAR(255) NOT NULL,
            confidence DOUBLE PRECISION NOT NULL DEFAULT 1.0,
            UNIQUE(cluster_id, member_type, member_key)
        );
        CREATE INDEX IF NOT EXISTS ix_cluster_member_key ON identity_cluster_members(member_key);

        CREATE TABLE IF NOT EXISTS session_devices (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL,
            device_id VARCHAR(36) NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS identities (
            id VARCHAR(36) PRIMARY KEY,
            display_name VARCHAR(200) NULL,
            primary_email VARCHAR(255) NOT NULL UNIQUE,
            trust_level VARCHAR(20) NOT NULL DEFAULT 'standard',
            system_role VARCHAR(30) NOT NULL DEFAULT 'user',
            mfa_secret VARCHAR(64) NULL,
            mfa_enabled BOOLEAN NOT NULL DEFAULT false,
            user_id VARCHAR(36) NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS permissions (
            id VARCHAR(36) PRIMARY KEY,
            code VARCHAR(80) NOT NULL UNIQUE
        );

        CREATE TABLE IF NOT EXISTS role_permissions (
            id VARCHAR(36) PRIMARY KEY,
            role VARCHAR(30) NOT NULL,
            permission_code VARCHAR(80) NOT NULL,
            UNIQUE(role, permission_code)
        );

        CREATE TABLE IF NOT EXISTS account_groups (
            id VARCHAR(36) PRIMARY KEY,
            cluster_id VARCHAR(36) NULL,
            name VARCHAR(120) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS break_glass_requests (
            id VARCHAR(36) PRIMARY KEY,
            requester_identity_id VARCHAR(36) NOT NULL,
            reason TEXT NOT NULL,
            approvals_needed INTEGER NOT NULL DEFAULT 2,
            approvals_count INTEGER NOT NULL DEFAULT 0,
            approved_by TEXT NOT NULL DEFAULT '',
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            resolved_at TIMESTAMPTZ NULL
        );

        CREATE TABLE IF NOT EXISTS subscriptions (
            id VARCHAR(36) PRIMARY KEY,
            profile_id VARCHAR(36) NOT NULL,
            tier VARCHAR(30) NOT NULL,
            billing_cycle VARCHAR(20) NOT NULL DEFAULT 'monthly',
            status VARCHAR(20) NOT NULL DEFAULT 'active',
            failed_payments INTEGER NOT NULL DEFAULT 0,
            next_retry_at TIMESTAMPTZ NULL,
            external_ref VARCHAR(120) NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS ix_subs_profile ON subscriptions(profile_id);

        CREATE TABLE IF NOT EXISTS subscription_invoices (
            id VARCHAR(36) PRIMARY KEY,
            subscription_id VARCHAR(36) NOT NULL,
            amount_usd DOUBLE PRECISION NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'open',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            paid_at TIMESTAMPTZ NULL,
            meta JSONB NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS sub_portfolios (
            id VARCHAR(36) PRIMARY KEY,
            profile_id VARCHAR(36) NOT NULL,
            name VARCHAR(120) NOT NULL,
            risk_budget DOUBLE PRECISION NOT NULL DEFAULT 1.0,
            strategy_tags JSONB NOT NULL DEFAULT '[]',
            is_master BOOLEAN NOT NULL DEFAULT false,
            master_portfolio_id VARCHAR(36) NULL REFERENCES sub_portfolios(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS ix_subport_profile ON sub_portfolios(profile_id);
        """
    )
    # Append-only hint for admission history: revoke update/delete from app role if exists.
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'appuser') THEN
            REVOKE UPDATE, DELETE ON admission_status_history FROM appuser;
            REVOKE UPDATE, DELETE ON audit_logs FROM appuser;
          END IF;
        EXCEPTION WHEN OTHERS THEN
          NULL;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS sub_portfolios CASCADE;
        DROP TABLE IF EXISTS subscription_invoices CASCADE;
        DROP TABLE IF EXISTS subscriptions CASCADE;
        DROP TABLE IF EXISTS break_glass_requests CASCADE;
        DROP TABLE IF EXISTS account_groups CASCADE;
        DROP TABLE IF EXISTS role_permissions CASCADE;
        DROP TABLE IF EXISTS permissions CASCADE;
        DROP TABLE IF EXISTS identities CASCADE;
        DROP TABLE IF EXISTS session_devices CASCADE;
        DROP TABLE IF EXISTS identity_cluster_members CASCADE;
        DROP TABLE IF EXISTS identity_clusters CASCADE;
        DROP TABLE IF EXISTS devices CASCADE;
        DROP TABLE IF EXISTS admission_status_history CASCADE;
        DROP TABLE IF EXISTS admission_cases CASCADE;
        DROP TABLE IF EXISTS access_policy_states CASCADE;
        ALTER TABLE profiles DROP COLUMN IF EXISTS access_level;
        """
    )
