"""Macro Registry tables and migration from draft macro_indicators.

Revision ID: 0022_macro_registry
Revises: 0021_forecast_snapshots
Create Date: 2026-07-19
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0022_macro_registry"
down_revision: Union[str, None] = "0021_forecast_snapshots"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS macro_source_registry (
            source_id               VARCHAR(64) PRIMARY KEY,
            category                VARCHAR(32) NOT NULL,
            symbol                  VARCHAR(64) NOT NULL,
            endpoint                TEXT NOT NULL,
            refresh_interval        VARCHAR(64) NOT NULL DEFAULT '0 8 * * *',
            priority                INTEGER NOT NULL DEFAULT 100,
            is_free                 BOOLEAN NOT NULL DEFAULT TRUE,
            fallback_source         VARCHAR(64) REFERENCES macro_source_registry(source_id),
            transformer             VARCHAR(128) NOT NULL,
            is_active               BOOLEAN NOT NULL DEFAULT TRUE,
            last_successful_refresh TIMESTAMPTZ,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_macro_source_registry_category_symbol
            ON macro_source_registry (category, symbol, priority)
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS macro_raw_responses (
            id              SERIAL PRIMARY KEY,
            source_id       VARCHAR(64) NOT NULL REFERENCES macro_source_registry(source_id),
            payload         TEXT NOT NULL,
            content_type    VARCHAR(128) NOT NULL DEFAULT 'application/json',
            http_status     INTEGER NOT NULL DEFAULT 200,
            payload_hash    VARCHAR(64) NOT NULL,
            fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT macro_raw_responses_source_hash_key UNIQUE (source_id, payload_hash)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_macro_raw_responses_source_fetched
            ON macro_raw_responses (source_id, fetched_at DESC)
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS macro_series_normalized (
            id                  SERIAL PRIMARY KEY,
            instrument          VARCHAR(64) NOT NULL,
            source_id           VARCHAR(64) NOT NULL REFERENCES macro_source_registry(source_id),
            raw_response_id     INTEGER NOT NULL REFERENCES macro_raw_responses(id),
            value               NUMERIC NOT NULL,
            currency            VARCHAR(8),
            unit                VARCHAR(32) NOT NULL,
            release_time        TIMESTAMPTZ NOT NULL,
            observation_time    TIMESTAMPTZ NOT NULL,
            period              VARCHAR(32) NOT NULL,
            revision            INTEGER NOT NULL DEFAULT 0,
            quality_flag        VARCHAR(16) NOT NULL DEFAULT 'ok',
            confidence          DOUBLE PRECISION NOT NULL DEFAULT 0.8,
            raw_payload_hash    VARCHAR(64) NOT NULL,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT macro_series_normalized_instrument_obs_rev_key
                UNIQUE (instrument, observation_time, source_id, revision)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_macro_series_normalized_instrument_obs
            ON macro_series_normalized (instrument, observation_time DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_macro_series_normalized_quality
            ON macro_series_normalized (instrument, quality_flag, release_time DESC)
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS macro_report_snapshots (
            id              VARCHAR(36) PRIMARY KEY,
            snapshot_type   VARCHAR(16) NOT NULL,
            as_of           TIMESTAMPTZ NOT NULL,
            payload         JSONB NOT NULL DEFAULT '{}',
            markdown        TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_macro_report_snapshots_type_asof
            ON macro_report_snapshots (snapshot_type, as_of DESC)
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS macro_series_history (
            id              SERIAL PRIMARY KEY,
            instrument      VARCHAR(64) NOT NULL,
            period          VARCHAR(32) NOT NULL,
            value           NUMERIC NOT NULL,
            quality_flag    VARCHAR(16) NOT NULL DEFAULT 'ok',
            as_of           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT macro_series_history_instrument_period_asof_key
                UNIQUE (instrument, period, as_of)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_macro_series_history_instrument_period
            ON macro_series_history (instrument, period, as_of DESC)
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS macro_calendar_entries (
            id                      SERIAL PRIMARY KEY,
            instrument              VARCHAR(64) NOT NULL,
            expected_release_time   TIMESTAMPTZ NOT NULL,
            period_covered          VARCHAR(32),
            source_id               VARCHAR(64) NOT NULL REFERENCES macro_source_registry(source_id),
            consensus_estimate      NUMERIC,
            fetched_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT macro_calendar_entries_instrument_release_source_key
                UNIQUE (instrument, expected_release_time, source_id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_macro_calendar_entries_release
            ON macro_calendar_entries (expected_release_time)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS macro_calendar_entries")
    op.execute("DROP TABLE IF EXISTS macro_series_history")
    op.execute("DROP TABLE IF EXISTS macro_report_snapshots")
    op.execute("DROP TABLE IF EXISTS macro_series_normalized")
    op.execute("DROP TABLE IF EXISTS macro_raw_responses")
    op.execute("DROP TABLE IF EXISTS macro_source_registry")
