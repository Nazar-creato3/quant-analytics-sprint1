"""Initial schema: all tables

Revision ID: 0001_initial
Revises:
Create Date: 2024-01-01 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── users ──────────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False, server_default="analyst"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("is_whitelisted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("last_login", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_users_email", "users", ["email"])

    # ── watchlists ─────────────────────────────────────────────────────────────
    op.create_table(
        "watchlists",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("tickers", postgresql.JSON(), nullable=False, server_default="[]"),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    # ── ohlcv_bars ─────────────────────────────────────────────────────────────
    op.create_table(
        "ohlcv_bars",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.String(20), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timeframe", sa.String(10), nullable=False),
        sa.Column("open", sa.Float(), nullable=False),
        sa.Column("high", sa.Float(), nullable=False),
        sa.Column("low", sa.Float(), nullable=False),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("volume", sa.Float(), nullable=False),
        sa.Column("vwap", sa.Float(), nullable=True),
        sa.Column("trade_count", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(50), nullable=False, server_default="unknown"),
        sa.UniqueConstraint("ticker", "timestamp", "timeframe", name="uq_ohlcv_bar"),
    )
    op.create_index("ix_ohlcv_ticker_ts", "ohlcv_bars", ["ticker", "timestamp"])

    # ── news_articles ──────────────────────────────────────────────────────────
    op.create_table(
        "news_articles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("url", sa.String(2048), nullable=False, unique=True),
        sa.Column("source", sa.String(100), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("sentiment_score", sa.Float(), nullable=True),
        sa.Column("sentiment_label", sa.String(20), nullable=True),
        sa.Column("tickers_mentioned", postgresql.JSON(), nullable=False, server_default="[]"),
        sa.Column("extracted_events", postgresql.JSON(), nullable=False, server_default="[]"),
        sa.Column("relevance_score", sa.Float(), nullable=False, server_default="0"),
    )
    op.create_index("ix_news_published", "news_articles", ["published_at"])

    # ── market_signals ─────────────────────────────────────────────────────────
    op.create_table(
        "market_signals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ticker", sa.String(20), nullable=False),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("signal_type", sa.String(50), nullable=False),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("strength", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("features", postgresql.JSON(), nullable=False, server_default="{}"),
        sa.Column("model_version", sa.String(50), nullable=True),
        sa.Column("price_at_signal", sa.Float(), nullable=True),
        sa.Column("expiry", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_signals_ticker", "market_signals", ["ticker"])
    op.create_index("ix_signals_generated", "market_signals", ["generated_at"])

    # ── maneuver_reports ───────────────────────────────────────────────────────
    op.create_table(
        "maneuver_reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("watchlist", postgresql.JSON(), nullable=False, server_default="[]"),
        sa.Column("pipeline_run_id", sa.String(36), nullable=False),
        sa.Column("text_summary", sa.Text(), nullable=True),
        sa.Column("regime", sa.String(50), nullable=True),
        sa.Column("market_context", postgresql.JSON(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(20), nullable=False, server_default="complete"),
    )
    op.create_index("ix_reports_created", "maneuver_reports", ["created_at"])

    # ── maneuvers ──────────────────────────────────────────────────────────────
    op.create_table(
        "maneuvers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "report_id",
            sa.String(36),
            sa.ForeignKey("maneuver_reports.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(20), nullable=False),
        sa.Column("strategy_type", sa.String(30), nullable=False),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("entry_zone_low", sa.Float(), nullable=True),
        sa.Column("entry_zone_high", sa.Float(), nullable=True),
        sa.Column("exit_zone_low", sa.Float(), nullable=True),
        sa.Column("exit_zone_high", sa.Float(), nullable=True),
        sa.Column("stop_loss", sa.Float(), nullable=True),
        sa.Column("take_profit", sa.Float(), nullable=True),
        sa.Column("invalidation_level", sa.Float(), nullable=True),
        sa.Column("risk_percent", sa.Float(), nullable=False),
        sa.Column("position_size_usd", sa.Float(), nullable=False),
        sa.Column("expected_return_low", sa.Float(), nullable=True),
        sa.Column("expected_return_high", sa.Float(), nullable=True),
        sa.Column("expected_pnl_low", sa.Float(), nullable=True),
        sa.Column("expected_pnl_high", sa.Float(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("time_horizon", sa.String(50), nullable=False),
        sa.Column("catalyst", sa.Text(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("execution_plan", sa.Text(), nullable=True),
        sa.Column("source_signals", postgresql.JSON(), nullable=False, server_default="[]"),
        sa.Column("source_news", postgresql.JSON(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("trading_mode", sa.String(10), nullable=False, server_default="paper"),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fill_price", sa.Float(), nullable=True),
        sa.Column("realized_pnl", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint("report_id", "rank", name="uq_maneuver_rank"),
    )
    op.create_index("ix_maneuver_report_id", "maneuvers", ["report_id"])
    op.create_index("ix_maneuver_ticker_status", "maneuvers", ["ticker", "status"])

    # ── execution_orders ───────────────────────────────────────────────────────
    op.create_table(
        "execution_orders",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "maneuver_id",
            sa.String(36),
            sa.ForeignKey("maneuvers.id"),
            nullable=False,
        ),
        sa.Column("broker_order_id", sa.String(100), nullable=True),
        sa.Column("ticker", sa.String(20), nullable=False),
        sa.Column("side", sa.String(10), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("order_type", sa.String(20), nullable=False),
        sa.Column("limit_price", sa.Float(), nullable=True),
        sa.Column("stop_price", sa.Float(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("trading_mode", sa.String(10), nullable=False),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fill_price", sa.Float(), nullable=True),
        sa.Column("fill_quantity", sa.Float(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("raw_response", postgresql.JSON(), nullable=False, server_default="{}"),
    )

    # ── backtest_runs ──────────────────────────────────────────────────────────
    op.create_table(
        "backtest_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("strategy", sa.String(100), nullable=False),
        sa.Column("ticker", sa.String(20), nullable=False),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("initial_capital", sa.Float(), nullable=False),
        sa.Column("final_capital", sa.Float(), nullable=True),
        sa.Column("total_return_pct", sa.Float(), nullable=True),
        sa.Column("sharpe_ratio", sa.Float(), nullable=True),
        sa.Column("max_drawdown_pct", sa.Float(), nullable=True),
        sa.Column("total_trades", sa.Integer(), nullable=True),
        sa.Column("win_rate", sa.Float(), nullable=True),
        sa.Column("parameters", postgresql.JSON(), nullable=False, server_default="{}"),
        sa.Column("equity_curve", postgresql.JSON(), nullable=False, server_default="[]"),
        sa.Column("trade_log", postgresql.JSON(), nullable=False, server_default="[]"),
        sa.Column("metrics", postgresql.JSON(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ── audit_logs ─────────────────────────────────────────────────────────────
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(50), nullable=True),
        sa.Column("resource_id", sa.String(36), nullable=True),
        sa.Column("details", postgresql.JSON(), nullable=False, server_default="{}"),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(256), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index("ix_audit_timestamp", "audit_logs", ["timestamp"])
    op.create_index("ix_audit_action", "audit_logs", ["action"])
    op.create_index("ix_audit_ts_action", "audit_logs", ["timestamp", "action"])


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("backtest_runs")
    op.drop_table("execution_orders")
    op.drop_table("maneuvers")
    op.drop_table("maneuver_reports")
    op.drop_table("market_signals")
    op.drop_table("news_articles")
    op.drop_table("ohlcv_bars")
    op.drop_table("watchlists")
    op.drop_table("users")
