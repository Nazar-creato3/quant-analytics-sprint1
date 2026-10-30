"""Device identity clustering (Prompt 58)."""
from __future__ import annotations

import hashlib
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field
from sqlalchemy import DateTime, Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.utils.helpers import new_uuid, utcnow


class ClusterMemberType(str, Enum):
    DEVICE = "device"
    IP_RANGE = "ip_range"
    USER = "user"
    PAYMENT_HASH = "payment_hash"


class DeviceORM(Base):
    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    fingerprint_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class IdentityClusterORM(Base):
    __tablename__ = "identity_clusters"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class IdentityClusterMemberORM(Base):
    __tablename__ = "identity_cluster_members"
    __table_args__ = (
        UniqueConstraint("cluster_id", "member_type", "member_key", name="uq_cluster_member"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    cluster_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("identity_clusters.id", ondelete="CASCADE"), nullable=False, index=True
    )
    member_type: Mapped[str] = mapped_column(String(30), nullable=False)
    member_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)


class SessionDeviceORM(Base):
    __tablename__ = "session_devices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    device_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class DeviceFingerprintIn(BaseModel):
    fingerprint: str = Field(min_length=8)
    user_agent: str | None = None


class DeviceFingerprintOut(BaseModel):
    device_id: str
    fingerprint_hash: str
    cluster_id: str | None = None


def hash_fingerprint(raw: str) -> str:
    return hashlib.sha256(raw.strip().encode("utf-8")).hexdigest()


def ip_range_key(ip: str | None) -> str | None:
    if not ip:
        return None
    parts = ip.split(".")
    if len(parts) == 4:
        return f"{parts[0]}.{parts[1]}.{parts[2]}.0/24"
    if ":" in ip:
        return ip.rsplit(":", 1)[0] + ":"
    return ip
