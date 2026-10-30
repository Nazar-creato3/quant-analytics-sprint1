"""
Prometheus metrics instrumentation.
Exposes /metrics endpoint and tracks:
- HTTP request counts/latency
- Pipeline runs + maneuver counts
- Trading execution events
- Model inference latency
- Cache hit/miss ratios
"""
from __future__ import annotations

import time
from typing import Callable

from fastapi import FastAPI, Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    Summary,
    generate_latest,
    multiprocess,
    CollectorRegistry,
)
from prometheus_client.core import CollectorRegistry as _Registry

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# ── Metric definitions ────────────────────────────────────────────────────────

http_requests_total = Counter(
    "apex_http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status_code"],
)

http_request_duration_seconds = Histogram(
    "apex_http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

pipeline_runs_total = Counter(
    "apex_pipeline_runs_total",
    "Total pipeline run attempts",
    ["status"],  # queued | complete | failed
)

maneuvers_generated_total = Counter(
    "apex_maneuvers_generated_total",
    "Total maneuvers generated",
    ["strategy_type", "is_tradeable"],
)

maneuver_approvals_total = Counter(
    "apex_maneuver_approvals_total",
    "Maneuver approval decisions",
    ["action"],  # approve | reject
)

execution_orders_total = Counter(
    "apex_execution_orders_total",
    "Execution orders submitted",
    ["ticker", "side", "trading_mode", "status"],
)

model_inference_duration_seconds = Histogram(
    "apex_model_inference_duration_seconds",
    "ML model inference latency",
    ["model_type"],
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0],
)

cache_hits_total = Counter(
    "apex_cache_hits_total",
    "Redis cache hits",
    ["namespace"],
)

cache_misses_total = Counter(
    "apex_cache_misses_total",
    "Redis cache misses",
    ["namespace"],
)

news_articles_ingested_total = Counter(
    "apex_news_articles_ingested_total",
    "Total news articles ingested",
    ["source"],
)

backtest_runs_total = Counter(
    "apex_backtest_runs_total",
    "Backtest runs",
    ["strategy", "status"],
)

active_pipeline_tasks = Gauge(
    "apex_active_pipeline_tasks",
    "Currently running pipeline tasks",
)

market_data_fetch_duration_seconds = Histogram(
    "apex_market_data_fetch_duration_seconds",
    "Market data fetch latency",
    ["provider", "ticker"],
    buckets=[0.05, 0.1, 0.5, 1.0, 3.0, 10.0],
)

portfolio_exposure_pct = Gauge(
    "apex_portfolio_exposure_pct",
    "Current portfolio exposure percentage",
)

daily_pnl_usd = Gauge(
    "apex_daily_pnl_usd",
    "Current day P&L in USD",
)


# ── FastAPI middleware ────────────────────────────────────────────────────────

def _normalize_path(path: str) -> str:
    """
    Normalize dynamic path segments to avoid high cardinality.
    e.g. /api/v1/maneuvers/abc123 → /api/v1/maneuvers/{id}
    """
    import re
    # UUIDs
    path = re.sub(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        "{id}",
        path,
    )
    # Pure numeric segments
    path = re.sub(r"/\d+", "/{int}", path)
    return path


async def metrics_middleware(request: Request, call_next: Callable) -> Response:
    """Track HTTP request counts and latency."""
    if not settings.PROMETHEUS_ENABLED:
        return await call_next(request)

    start = time.perf_counter()
    method = request.method
    path = _normalize_path(request.url.path)

    try:
        response = await call_next(request)
        status = str(response.status_code)
    except Exception:
        status = "500"
        raise
    finally:
        duration = time.perf_counter() - start
        http_requests_total.labels(
            method=method, endpoint=path, status_code=status
        ).inc()
        http_request_duration_seconds.labels(
            method=method, endpoint=path
        ).observe(duration)

    return response


# ── Metrics endpoint ──────────────────────────────────────────────────────────

def setup_metrics(app: FastAPI) -> None:
    """Register the /metrics endpoint and HTTP middleware."""
    if not settings.PROMETHEUS_ENABLED:
        return

    app.middleware("http")(metrics_middleware)

    @app.get("/metrics", include_in_schema=False)
    async def metrics_endpoint() -> Response:
        """Prometheus scrape endpoint."""
        data = generate_latest()
        return Response(content=data, media_type=CONTENT_TYPE_LATEST)

    logger.info("Prometheus metrics enabled at /metrics")


# ── Context-manager timers ────────────────────────────────────────────────────

class _Timer:
    """Measure elapsed time and record to a histogram."""

    def __init__(self, histogram: Histogram, labels: dict) -> None:
        self._hist = histogram
        self._labels = labels
        self._start = 0.0

    def __enter__(self) -> "_Timer":
        self._start = time.perf_counter()
        return self

    def __exit__(self, *_) -> None:
        elapsed = time.perf_counter() - self._start
        self._hist.labels(**self._labels).observe(elapsed)


def time_model_inference(model_type: str) -> _Timer:
    return _Timer(model_inference_duration_seconds, {"model_type": model_type})


def time_market_fetch(provider: str, ticker: str) -> _Timer:
    return _Timer(market_data_fetch_duration_seconds, {"provider": provider, "ticker": ticker})
