"""Database connection config: app runtime vs migration URLs."""
from __future__ import annotations

from app.core.config import Settings


def test_app_runtime_url_uses_app_db_user():
    s = Settings(
        APP_DB_USER="appuser",
        APP_DB_PASSWORD="app-secret",
        POSTGRES_USER="apex",
        POSTGRES_PASSWORD="apex-secret",
        _env_file=None,
    )
    assert "appuser" in s.DATABASE_URL
    assert "app-secret" in s.DATABASE_URL
    assert "apex" not in s.DATABASE_URL.split("@")[0]


def test_migration_url_uses_postgres_superuser():
    s = Settings(
        APP_DB_USER="appuser",
        APP_DB_PASSWORD="app-secret",
        POSTGRES_USER="apex",
        POSTGRES_PASSWORD="apex-secret",
        _env_file=None,
    )
    assert "apex" in s.MIGRATION_DATABASE_URL_SYNC
    assert "apex-secret" in s.MIGRATION_DATABASE_URL_SYNC
