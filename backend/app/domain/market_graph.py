"""ORM mapping for market graph edges (Prompt 20)."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class MarketGraphEdgeORM(Base):
    """Directed weighted edge in the market relationship graph."""

    __tablename__ = "market_graph_edges"

    from_node: Mapped[str] = mapped_column(Text, primary_key=True)
    to_node: Mapped[str] = mapped_column(Text, primary_key=True)
    edge_type: Mapped[str] = mapped_column(Text, primary_key=True)
    weight: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
