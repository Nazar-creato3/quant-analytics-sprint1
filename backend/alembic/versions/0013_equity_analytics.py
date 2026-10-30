"""Equity analytics tables — earnings, corporate actions, computed snapshots.

Revision ID: 0013_equity_analytics
Revises: 0012_compliance_access
Create Date: 2026-07-18
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0013_equity_analytics"
down_revision: Union[str, None] = "0012_compliance_access"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS earnings_calendar (
            id              VARCHAR(36) PRIMARY KEY,
            symbol          VARCHAR(20) NOT NULL,
            instrument_id   INTEGER,
            report_date     TIMESTAMPTZ NOT NULL,
            fiscal_period   VARCHAR(10),
            eps_estimate    NUMERIC(12, 4),
            eps_actual      NUMERIC(12, 4),
            source          VARCHAR(50) NOT NULL DEFAULT 'yfinance',
            raw_data        JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_earnings_calendar_symbol ON earnings_calendar (symbol)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_earnings_calendar_report_date ON earnings_calendar (report_date)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS corporate_actions (
            id              VARCHAR(36) PRIMARY KEY,
            symbol          VARCHAR(20) NOT NULL,
            instrument_id   INTEGER,
            action_type     VARCHAR(30) NOT NULL,
            effective_date  TIMESTAMPTZ NOT NULL,
            details         JSONB NOT NULL DEFAULT '{}'::jsonb,
            source          VARCHAR(50) NOT NULL DEFAULT 'yfinance',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_corporate_actions_symbol ON corporate_actions (symbol)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_corporate_actions_effective_date ON corporate_actions (effective_date)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS dividend_events (
            id                  VARCHAR(36) PRIMARY KEY,
            symbol              VARCHAR(20) NOT NULL,
            instrument_id       INTEGER,
            ex_dividend_date    TIMESTAMPTZ NOT NULL,
            payment_date        TIMESTAMPTZ,
            record_date         TIMESTAMPTZ,
            amount              NUMERIC(12, 6) NOT NULL,
            currency            VARCHAR(3) NOT NULL DEFAULT 'USD',
            source              VARCHAR(50) NOT NULL DEFAULT 'yfinance',
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_dividend_events_symbol ON dividend_events (symbol)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_dividend_events_ex_date ON dividend_events (ex_dividend_date)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS split_history (
            id              VARCHAR(36) PRIMARY KEY,
            symbol          VARCHAR(20) NOT NULL,
            instrument_id   INTEGER,
            split_date      TIMESTAMPTZ NOT NULL,
            ratio           NUMERIC(12, 6) NOT NULL,
            source          VARCHAR(50) NOT NULL DEFAULT 'yfinance',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_split_history_symbol ON split_history (symbol)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS sector_rotation_score (
            id              VARCHAR(36) PRIMARY KEY,
            sector          VARCHAR(80) NOT NULL,
            as_of_date      DATE NOT NULL,
            score           DOUBLE PRECISION NOT NULL,
            metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_sector_rotation_sector ON sector_rotation_score (sector)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS market_session_profile (
            id                  VARCHAR(36) PRIMARY KEY,
            symbol              VARCHAR(20) NOT NULL,
            instrument_id       INTEGER,
            session_type        VARCHAR(20) NOT NULL,
            avg_return_pct      DOUBLE PRECISION NOT NULL DEFAULT 0,
            avg_volume_ratio    DOUBLE PRECISION NOT NULL DEFAULT 0,
            volatility          DOUBLE PRECISION NOT NULL DEFAULT 0,
            computed_at         TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_market_session_profile_symbol ON market_session_profile (symbol)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS liquidity_filter (
            id                      VARCHAR(36) PRIMARY KEY,
            symbol                  VARCHAR(20) NOT NULL,
            instrument_id           INTEGER,
            min_volume_threshold    INTEGER NOT NULL,
            avg_volume_20d          INTEGER NOT NULL,
            passes_filter           BOOLEAN NOT NULL DEFAULT false,
            computed_at             TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_liquidity_filter_symbol ON liquidity_filter (symbol)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS volatility_by_regime (
            id              VARCHAR(36) PRIMARY KEY,
            symbol          VARCHAR(20) NOT NULL,
            instrument_id   INTEGER,
            regime          VARCHAR(20) NOT NULL,
            realized_vol    DOUBLE PRECISION NOT NULL,
            computed_at     TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_volatility_by_regime_symbol ON volatility_by_regime (symbol)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS news_impact_score (
            id                      VARCHAR(36) PRIMARY KEY,
            symbol                  VARCHAR(20) NOT NULL,
            instrument_id           INTEGER,
            score                   DOUBLE PRECISION NOT NULL,
            article_count           INTEGER NOT NULL DEFAULT 0,
            nearest_event_hours     DOUBLE PRECISION,
            computed_at             TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_news_impact_score_symbol ON news_impact_score (symbol)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS news_impact_score")
    op.execute("DROP TABLE IF EXISTS volatility_by_regime")
    op.execute("DROP TABLE IF EXISTS liquidity_filter")
    op.execute("DROP TABLE IF EXISTS market_session_profile")
    op.execute("DROP TABLE IF EXISTS sector_rotation_score")
    op.execute("DROP TABLE IF EXISTS split_history")
    op.execute("DROP TABLE IF EXISTS dividend_events")
    op.execute("DROP TABLE IF EXISTS corporate_actions")
    op.execute("DROP TABLE IF EXISTS earnings_calendar")
