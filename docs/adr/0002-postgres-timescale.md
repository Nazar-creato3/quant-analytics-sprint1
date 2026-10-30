# ADR 0002 — PostgreSQL 18 + TimescaleDB 2.30.2

Статус: **внедрено в 01A-pg18** (D-00A-1 п.3).

Образ: `timescale/timescaledb:2.30.2-pg18` (PG 18.x, Timescale 2.30.2).  
Источник тега: https://hub.docker.com/r/timescale/timescaledb/tags

Том `postgres_data_pg18` — отдельный от PG15 `postgres_data`. Старый каталог не монтировать (нужен dump/restore или `pg_upgrade`). Боевых данных нет.

Проверки в `test_testcontainers_optional.py`: `server_version_num` ≥ 180000, extension 2.30.x, GENERATED ALWAYS AS без STORED → `attgenerated = 'v'` (VIRTUAL), hypertable + `count(*)` + EXPLAIN.
