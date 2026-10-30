"""ORM models for per-user trading keys (Flow B)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class TradingKeyMetadataORM(Base):
    __tablename__ = "trading_key_metadata"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    venue: Mapped[str] = mapped_column(String(32), index=True)
    provider_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    account_mode: Mapped[str] = mapped_column(String(10), default="live", server_default="live")
    label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    vault_path: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="active", server_default="active")
    permission_check_status: Mapped[str] = mapped_column(String(32), default="skipped", server_default="skipped")
    withdraw_allowed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    permission_warning: Mapped[str | None] = mapped_column(Text, nullable=True)
    account_display: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_health_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_health_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rotation_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("user_id", "venue", "account_mode", name="uq_trading_key_user_venue_mode"),
    )


class TradingKeySecretORM(Base):
    __tablename__ = "trading_key_secrets"

    key_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("trading_key_metadata.id", ondelete="CASCADE"),
        primary_key=True,
    )
    encrypted_payload: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TradingKeyAuditORM(Base):
    __tablename__ = "trading_key_audit"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    key_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    venue: Mapped[str | None] = mapped_column(String(32), nullable=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    actor_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
