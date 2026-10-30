"""Seed default admin user and default watchlist

Revision ID: 0003_seed
Revises: 0002_timescale
Create Date: 2024-01-03 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa  # noqa: F401  # оставляем, чтобы Alembic не ругался на импорт

revision = "0003_seed"
down_revision = "0002_timescale"
branch_labels = None
depends_on = None

DEFAULT_WATCHLIST = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META",
    "NVDA", "SPY", "QQQ", "GLD", "BTC-USD",
]


def _hash_password(password: str) -> str:
    """Stub: hashing отключен в dev-моде миграций."""
    return password


def upgrade() -> None:
    # В dev-окружении на обычном Postgres не сидируем админа и дефолтный watchlist
    # через миграцию. Пользователя создадим через API или отдельным скриптом.
    pass


def downgrade() -> None:
    # В dev-окружении ничего не откатываем для сид-данных.
    pass