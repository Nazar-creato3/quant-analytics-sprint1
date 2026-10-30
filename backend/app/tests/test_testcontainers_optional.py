"""Live Testcontainers: TimescaleDB on PostgreSQL 18 + Redis. Requires Docker."""
from __future__ import annotations

import pytest

pytest.importorskip("testcontainers")
pytest.importorskip("redis")
pytest.importorskip("sqlalchemy")

TS_IMAGE = "timescale/timescaledb:2.30.2-pg18"


def test_timescaledb_pg18_and_redis_containers():
    from redis import Redis
    from sqlalchemy import create_engine, text
    from testcontainers.postgres import PostgresContainer
    from testcontainers.redis import RedisContainer

    with (
        PostgresContainer(TS_IMAGE) as pg,
        RedisContainer("redis:7-alpine") as redis_c,
    ):
        engine = create_engine(pg.get_connection_url())
        with engine.connect() as conn:
            major = conn.execute(text("SHOW server_version_num")).scalar()
            assert int(major) >= 180000
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb"))
            ext = conn.execute(
                text("SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'")
            ).scalar()
            assert ext and ext.startswith("2.30")

            conn.execute(
                text(
                    """
                    CREATE TABLE qa_gen (
                        id int PRIMARY KEY,
                        n int,
                        doubled int GENERATED ALWAYS AS (n * 2)
                    )
                    """
                )
            )
            stored = conn.execute(
                text(
                    """
                    SELECT a.attgenerated
                    FROM pg_attribute a
                    JOIN pg_class c ON c.oid = a.attrelid
                    WHERE c.relname = 'qa_gen' AND a.attname = 'doubled'
                    """
                )
            ).scalar()
            # PG18 default for GENERATED ALWAYS AS (...) is VIRTUAL ('v'), not STORED ('s').
            assert stored == "v"
            conn.execute(text("INSERT INTO qa_gen (id, n) VALUES (1, 4)"))
            assert conn.execute(text("SELECT doubled FROM qa_gen WHERE id = 1")).scalar() == 8

            conn.execute(
                text(
                    """
                    CREATE TABLE qa_bars (
                        ts timestamptz NOT NULL,
                        px double precision
                    )
                    """
                )
            )
            conn.execute(text("SELECT create_hypertable('qa_bars', 'ts')"))
            conn.execute(
                text("INSERT INTO qa_bars VALUES (now(), 1.0), (now() - interval '1 hour', 2.0)")
            )
            n = conn.execute(text("SELECT count(*) FROM qa_bars")).scalar()
            assert n == 2
            plan = conn.execute(text("EXPLAIN SELECT count(*) FROM qa_bars")).fetchall()
            plan_txt = "\n".join(str(row[0]) for row in plan)
            assert "Aggregate" in plan_txt or "count" in plan_txt.lower()

        client = Redis(
            host=redis_c.get_container_host_ip(),
            port=int(redis_c.get_exposed_port(6379)),
        )
        assert client.ping() is True
        client.set("qa:probe", "1")
        assert client.get("qa:probe") == b"1"
