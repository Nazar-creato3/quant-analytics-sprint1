# Realtime Market Data Layer

## TimescaleDB choice

**We merge with the existing `postgres` service** — do not add a separate TimescaleDB container.

The main `docker-compose.yml` already runs `timescale/timescaledb:latest-pg15` as the `postgres` service on port 5432 with database `apex_intel`. This keeps one PostgreSQL instance for both the FastAPI app (Alembic migrations, `ohlcv_bars`, users, etc.) and the new realtime pipeline tables (`instruments`, `trades`, `ohlcv`, `derivatives_metrics`, `news`).

A separate TimescaleDB service (as in the archive `files_extracted/docker-compose.yml`) would duplicate Redis/Postgres, conflict on port 5432, and split data across two databases. That approach is intentionally **not** used here.

### Schema application

| Path | When it runs |
|------|----------------|
| `infrastructure/docker/init-timescale.sql` | First boot of a **new** Postgres volume — enables the TimescaleDB extension |
| `backend/alembic/versions/0006_market_data_realtime.py` | All deployments — creates pipeline tables; hypertables when TimescaleDB is present |
| `backend/data/schema.sql` | Reference / manual apply; mirrors the Alembic migration |

## Connectors

| Connector | API key | Status |
|-----------|---------|--------|
| `binance-ws` | None (public WebSocket) | **Enabled** |
| `moex-iss` | None (public ISS) | **Enabled** |
| `tinkoff-client` | `TINKOFF_TOKEN` (or `TINKOFF_API_TOKEN`) | **Enabled** — `data-pipeline` profile |
| `news-aggregator` | Optional news API keys | **Enabled** |
| `stream-consumer` | None | **Enabled** |
| `coinglass-client` | Paid API | **Disabled / skip** |

### Deprecated: `coinglass_client.py`

**Do not run or deploy.** Coinglass requires a paid API key; the service is commented out in `docker-compose.data.yml` and the stream consumer no longer ingests `raw:coinglass:derivatives`. The script remains in `backend/connectors/` for reference only.

Finam (`FINAM_API_KEY`) is wired for **grid_bot** venue connectivity only; there is no Finam data-pipeline connector in this repo yet.

## Data flow

```
Connectors (binance_ws, moex_iss, tinkoff_client, …) → Redis Streams → consumer.py → TimescaleDB
news_aggregator.py ──────────────────────────────────────────────→ TimescaleDB (news)
```

## Running the pipeline

Development (overlay — does not change default `docker compose up`):

```bash
docker compose -f docker-compose.yml -f docker-compose.data.yml --profile data-pipeline up -d
```

Production (same overlay; connectors use `restart: unless-stopped`):

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.data.yml --profile data-pipeline up -d
```

Set `TINKOFF_TOKEN` (or `TINKOFF_API_TOKEN`) in `.env` before starting — the tinkoff-client container requires it.
