"""Migration-level append-only enforcement for audit_logs."""
from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_APPEND_ONLY_PG_URL"),
    reason="Set TEST_APPEND_ONLY_PG_URL to a PostgreSQL test database to run REVOKE tests",
)


@pytest.fixture
def pg_engine():
    url = os.environ["TEST_APPEND_ONLY_PG_URL"]
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                DO $$
                BEGIN
                  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'appuser') THEN
                    CREATE ROLE appuser NOLOGIN;
                  END IF;
                END $$;
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id SERIAL PRIMARY KEY,
                    action VARCHAR(100) NOT NULL,
                    timestamp TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
        )
        conn.execute(text("REVOKE UPDATE, DELETE ON audit_logs FROM appuser"))
        conn.execute(text("GRANT SELECT, INSERT ON audit_logs TO appuser"))
    yield engine
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS audit_logs"))


def test_appuser_cannot_update_audit_logs(pg_engine):
    with pg_engine.begin() as conn:
        conn.execute(text("INSERT INTO audit_logs (action) VALUES ('seed')"))
    with pg_engine.connect() as conn:
        conn.execute(text("SET ROLE appuser"))
        with pytest.raises(Exception) as exc:
            conn.execute(text("UPDATE audit_logs SET action = 'tampered' WHERE id = 1"))
        assert "permission denied" in str(exc.value).lower()


def test_appuser_cannot_delete_audit_logs(pg_engine):
    with pg_engine.connect() as conn:
        conn.execute(text("SET ROLE appuser"))
        with pytest.raises(Exception) as exc:
            conn.execute(text("DELETE FROM audit_logs"))
        assert "permission denied" in str(exc.value).lower()
