-- TimescaleDB initialization
-- This runs once when the container is first created.

-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

-- Grant privileges
GRANT ALL PRIVILEGES ON DATABASE apex_intel TO apex;

-- Note: The ohlcv_bars hypertable conversion happens in Alembic migration
-- after SQLAlchemy creates the table. See migrations/versions/0002_timescale.py
--
-- Realtime pipeline tables (instruments, market_trades, ohlcv, derivatives_metrics, news)
-- are created by Alembic migration 0006_market_data_realtime. Reference SQL:
-- backend/data/schema.sql
