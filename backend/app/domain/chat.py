"""In-app chat domain — Conversation + Message (Prompt 75)."""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field
from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.utils.helpers import new_uuid, utcnow


class ConversationStatus(str, Enum):
    OPEN = "open"
    RESOLVED = "resolved"
    ARCHIVED = "archived"


class MessageSenderRole(str, Enum):
    CLIENT = "client"
    OPERATOR_ADMIN = "operator_admin"
    OWNER_ADMIN = "owner_admin"
    ADVISOR_AI = "advisor_ai"


class ConversationORM(Base):
    __tablename__ = "chat_conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    client_profile_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    assigned_admin_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("identities.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ConversationStatus.OPEN.value, index=True
    )
    related_deal_intent_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("deal_intents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    related_symbol: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class MessageORM(Base):
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    conversation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("chat_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sender_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    sender_role: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    attachment_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ConversationRead(BaseModel):
    id: str
    client_profile_id: str
    assigned_admin_id: str | None = None
    status: ConversationStatus
    related_deal_intent_id: str | None = None
    related_symbol: str | None = None
    title: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class MessageRead(BaseModel):
    id: str
    conversation_id: str
    sender_id: str
    sender_role: MessageSenderRole
    body: str
    attachment_url: str | None = None
    created_at: datetime
    read_at: datetime | None = None

    model_config = {"from_attributes": True}


class ConversationCreate(BaseModel):
    related_deal_intent_id: str | None = None
    related_symbol: str | None = Field(default=None, max_length=32)
    initial_message: str | None = Field(default=None, min_length=1)


class MessageCreate(BaseModel):
    body: str = Field(min_length=1, max_length=8000)
    attachment_url: str | None = Field(default=None, max_length=500)
