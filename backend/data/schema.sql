-- Apex Intel realtime market data schema (TimescaleDB)
-- Applied via Alembic migration 0006_market_data_realtime on existing deployments.
-- Fresh containers also enable the extension in infrastructure/docker/init-timescale.sql.

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Instrument registry (crypto, MOEX/SPB equities, etc.)
CREATE TABLE IF NOT EXISTS instruments (
    id              SERIAL PRIMARY KEY,
    symbol          TEXT NOT NULL,
    source          TEXT NOT NULL,
    instrument_type TEXT NOT NULL,
    figi            TEXT,
    category        TEXT,
    tradable_unit   TEXT NOT NULL DEFAULT 'per_share',
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE (symbol, source)
);

-- Capital sleeves within a trading profile (domain model, migration 0007)
CREATE TABLE IF NOT EXISTS sleeves (
    id                      VARCHAR(36) PRIMARY KEY,
    profile_id              VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name                    VARCHAR(100) NOT NULL,
    category                VARCHAR(40) NOT NULL,
    capital_allocation_pct  NUMERIC(5, 2) NOT NULL
        CHECK (capital_allocation_pct >= 0 AND capital_allocation_pct <= 100),
    risk_budget             NUMERIC(18, 6) NOT NULL CHECK (risk_budget >= 0),
    status                  VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_sleeves_profile_id ON sleeves (profile_id);

-- Raw exchange trades / ticks (separate from app trading_accounts.trades)
CREATE TABLE IF NOT EXISTS market_trades (
    time          TIMESTAMPTZ NOT NULL,
    instrument_id INT NOT NULL REFERENCES instruments(id),
    price         NUMERIC NOT NULL,
    quantity      NUMERIC NOT NULL,
    side          TEXT,
    trade_id      BIGINT
);
SELECT create_hypertable('market_trades', 'time', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_market_trades_instrument_time ON market_trades (instrument_id, time DESC);

-- OHLCV aggregates for charting
CREATE TABLE IF NOT EXISTS ohlcv (
    time          TIMESTAMPTZ NOT NULL,
    instrument_id INT NOT NULL REFERENCES instruments(id),
    timeframe     TEXT NOT NULL,
    open          NUMERIC,
    high          NUMERIC,
    low           NUMERIC,
    close         NUMERIC,
    volume        NUMERIC
);
SELECT create_hypertable('ohlcv', 'time', if_not_exists => TRUE);
CREATE UNIQUE INDEX IF NOT EXISTS idx_ohlcv_unique ON ohlcv (instrument_id, timeframe, time);

-- Derivatives metrics (Coinglass: funding, OI, liquidations)
CREATE TABLE IF NOT EXISTS derivatives_metrics (
    time          TIMESTAMPTZ NOT NULL,
    instrument_id INT NOT NULL REFERENCES instruments(id),
    metric_type   TEXT NOT NULL,
    value         NUMERIC NOT NULL,
    side          TEXT
);
SELECT create_hypertable('derivatives_metrics', 'time', if_not_exists => TRUE);

-- RSS / news feed items (separate from app news_articles table)
CREATE TABLE IF NOT EXISTS news (
    id            SERIAL PRIMARY KEY,
    published_at  TIMESTAMPTZ NOT NULL,
    source        TEXT NOT NULL,
    title         TEXT NOT NULL,
    url           TEXT NOT NULL UNIQUE,
    summary       TEXT,
    sentiment     NUMERIC,
    tags          TEXT[],
    created_at    TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_news_published ON news (published_at DESC);
