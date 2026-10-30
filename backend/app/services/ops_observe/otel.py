"""OpenTelemetry SDK for FastAPI, SQLAlchemy, Celery, Redis, httpx, gRPC.

Instrumentation packages on PyPI are 0.xxbN. This module uses only the
stable API/SDK 1.x and wraps call sites we own. Collector is optional:
unset OTEL_EXPORTER_OTLP_ENDPOINT keeps an in-memory exporter.

Docs: https://opentelemetry.io/docs/languages/python/
"""
from __future__ import annotations

import os
from typing import Any

from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import Status, StatusCode

from app.services.qa.feature_flags import is_enabled

SERVICE_NAME = "apex-intel-api"
_started = False
_memory_spans = InMemorySpanExporter()
_metric_reader = InMemoryMetricReader()
_httpx_wrapped = False
_redis_wrapped = False
_grpc_wrapped = False
_sqlalchemy_wrapped = False
_celery_wrapped = False


class _SilentOTLP(SpanExporter):
    """OTLP HTTP exporter that never raises into the request path."""

    def __init__(self, endpoint: str) -> None:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )

        self._inner = OTLPSpanExporter(endpoint=endpoint.rstrip("/") + "/v1/traces")

    def export(self, spans: Any) -> SpanExportResult:
        try:
            return self._inner.export(spans)
        except Exception:  # noqa: BLE001 — collector down must not fail the request
            return SpanExportResult.FAILURE

    def shutdown(self) -> None:
        try:
            self._inner.shutdown()
        except Exception:  # noqa: BLE001
            return

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        try:
            return bool(self._inner.force_flush(timeout_millis=timeout_millis))
        except Exception:  # noqa: BLE001
            return False


def _on() -> bool:
    return is_enabled("qa_ops_observe")


def otlp_endpoint() -> str:
    return (os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or "").strip()


def setup() -> None:
    """Idempotent TracerProvider. Safe when the collector is down."""
    global _started
    if _started or not _on():
        return
    resource = Resource.create({"service.name": SERVICE_NAME, "service.namespace": "qa"})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(SimpleSpanProcessor(_memory_spans))
    endpoint = otlp_endpoint()
    if endpoint:
        provider.add_span_processor(BatchSpanProcessor(_SilentOTLP(endpoint)))
    trace.set_tracer_provider(provider)
    metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[_metric_reader]))
    _started = True
    _wrap_httpx()
    _wrap_redis()
    _wrap_grpc()
    _wrap_sqlalchemy()
    _wrap_celery()


def tracer():
    setup()
    return trace.get_tracer("ops_observe")


def start_otel_span(name: str, request_id: str = "") -> Any:
    span = tracer().start_span(name)
    if request_id:
        span.set_attribute("qa.request_id", request_id)
    return span


def recorded_span_names() -> list[str]:
    return [span.name for span in _memory_spans.get_finished_spans()]


def reset_spans() -> None:
    _memory_spans.clear()


def _wrap_httpx() -> None:
    global _httpx_wrapped
    if _httpx_wrapped:
        return
    try:
        import httpx
    except ImportError:
        return

    original = httpx.AsyncClient.request

    async def traced(self: Any, method: Any, url: Any, *args: Any, **kwargs: Any) -> Any:
        with tracer().start_as_current_span("httpx.request") as span:
            span.set_attribute("http.method", str(method))
            span.set_attribute("url.full", str(url))
            try:
                return await original(self, method, url, *args, **kwargs)
            except Exception as exc:
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                raise

    httpx.AsyncClient.request = traced  # type: ignore[method-assign]
    _httpx_wrapped = True


def _wrap_redis() -> None:
    global _redis_wrapped
    if _redis_wrapped:
        return
    try:
        import redis.asyncio as redis_async
    except ImportError:
        return
    client_cls = getattr(redis_async, "Redis", None)
    if client_cls is None or not hasattr(client_cls, "execute_command"):
        return
    original = client_cls.execute_command

    async def traced(self: Any, *args: Any, **kwargs: Any) -> Any:
        name = str(args[0]) if args else "redis"
        with tracer().start_as_current_span("redis.command") as span:
            span.set_attribute("db.system", "redis")
            span.set_attribute("db.operation", name)
            return await original(self, *args, **kwargs)

    client_cls.execute_command = traced  # type: ignore[method-assign]
    _redis_wrapped = True


def _wrap_grpc() -> None:
    global _grpc_wrapped
    if _grpc_wrapped:
        return
    try:
        import grpc
    except ImportError:
        return
    original = grpc.insecure_channel

    def traced(target: Any, *args: Any, **kwargs: Any) -> Any:
        with tracer().start_as_current_span("grpc.channel") as span:
            span.set_attribute("rpc.system", "grpc")
            span.set_attribute("server.address", str(target))
            return original(target, *args, **kwargs)

    grpc.insecure_channel = traced  # type: ignore[method-assign]
    if hasattr(grpc, "secure_channel"):
        orig_secure = grpc.secure_channel

        def traced_secure(target: Any, *args: Any, **kwargs: Any) -> Any:
            with tracer().start_as_current_span("grpc.channel") as span:
                span.set_attribute("rpc.system", "grpc")
                span.set_attribute("server.address", str(target))
                return orig_secure(target, *args, **kwargs)

        grpc.secure_channel = traced_secure  # type: ignore[method-assign]
    _grpc_wrapped = True


def _wrap_sqlalchemy() -> None:
    global _sqlalchemy_wrapped
    if _sqlalchemy_wrapped:
        return
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    @event.listens_for(Engine, "before_cursor_execute")
    def _before(conn: Any, cursor: Any, statement: Any, parameters: Any, context: Any, executemany: Any) -> None:
        del conn, cursor, parameters, executemany
        context._qa_span = tracer().start_span("sqlalchemy.query")
        context._qa_span.set_attribute("db.system", "postgresql")
        context._qa_span.set_attribute("db.statement", str(statement)[:200])

    @event.listens_for(Engine, "after_cursor_execute")
    def _after(conn: Any, cursor: Any, statement: Any, parameters: Any, context: Any, executemany: Any) -> None:
        del conn, cursor, statement, parameters, executemany
        span = getattr(context, "_qa_span", None)
        if span is not None:
            span.end()

    _sqlalchemy_wrapped = True


def _wrap_celery() -> None:
    global _celery_wrapped
    if _celery_wrapped:
        return
    try:
        from celery.signals import task_failure, task_prerun
    except ImportError:
        return

    @task_prerun.connect
    def _prerun(sender: Any = None, task_id: str = "", **kwargs: Any) -> None:
        del kwargs
        name = getattr(sender, "name", "celery.task")
        span = tracer().start_span("celery.task")
        span.set_attribute("messaging.system", "celery")
        span.set_attribute("celery.task_id", task_id)
        span.set_attribute("celery.task", str(name))
        span.end()

    @task_failure.connect
    def _fail(sender: Any = None, exception: Any = None, **kwargs: Any) -> None:
        del kwargs
        with tracer().start_as_current_span("celery.task.failure") as span:
            span.set_status(Status(StatusCode.ERROR, str(exception)))
            span.set_attribute("celery.task", str(getattr(sender, "name", "")))

    _celery_wrapped = True


def instrument_fastapi(app: Any) -> None:
    setup()
    if getattr(app.state, "qa_otel", False):
        return
    app.state.qa_otel = True
