"""Latency, alerts, last-known values, and OpenTelemetry spans."""
from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.services.ops_observe.otel import otlp_endpoint, recorded_span_names
from app.services.ops_observe.otel import setup as setup_otel
from app.services.qa.feature_flags import is_enabled, snapshot

MODEL_VERSION = "ops_observe.v1"
_MISSING = "нет данных"
_ROOT = Path(__file__).resolve().parents[4]
_RUNBOOKS = _ROOT / "docs" / "ops" / "runbooks"
_CONFIG = Path(__file__).with_name("config.json")
_DRILLS = {
    "data-provider": "market_data",
    "broker": "broker",
    "queue-overflow": "event_bus",
    "backup-restore": "backup",
    "release-rollback": "release",
    "key-compromise": "venue_keys",
}
_SECRET_KEYS = {"password", "token", "secret", "api_key", "authorization"}

_latency_ms: list[float] = []
_report_seconds: list[float] = []
_errors: list[str] = []
_last: dict[str, str] = {}
_alerts: list[dict[str, str]] = []
_logs: list[dict[str, str]] = []
_spans: list[dict[str, str]] = []
_shadow: int = 0


def reset() -> None:
    global _shadow
    _latency_ms.clear()
    _report_seconds.clear()
    _errors.clear()
    _last.clear()
    _alerts.clear()
    _logs.clear()
    _spans.clear()
    _shadow = 0


def _cfg() -> dict[str, Any]:
    return json.loads(_CONFIG.read_text(encoding="utf-8"))


def _on() -> bool:
    return is_enabled("qa_ops_observe")


def record_latency(ms: float) -> None:
    if _on():
        _latency_ms.append(float(ms))


def record_report_seconds(seconds: float) -> None:
    if _on():
        _report_seconds.append(float(seconds))


def record_error(code: str) -> None:
    if _on():
        _errors.append(code)


def remember(service: str, value: str) -> None:
    if _on() and value not in ("", None):
        _last[service] = str(value)


def record_shadow_diff() -> None:
    global _shadow
    if _on():
        _shadow += 1


def read_degraded(service: str, *, failed: bool) -> dict[str, str]:
    known = _last.get(service)
    if not failed:
        return {"value": known or _MISSING, "mark": "текущее" if known else _MISSING, "status": "ok"}
    if not known:
        return {"value": _MISSING, "mark": _MISSING, "status": "degraded"}
    return {"value": known, "mark": "последнее известное", "status": "degraded"}


def note_failure(service: str, reason: str) -> dict[str, str]:
    alert = {"name": f"{service}.down", "service": service, "reason": reason, "at": datetime.now(UTC).isoformat()}
    if _on():
        _alerts.append(alert)
    return alert


def log_event(request_id: str, event: str, **fields: str) -> dict[str, str]:
    row = {
        "request_id": request_id or _MISSING,
        "event": event,
        "at": datetime.now(UTC).isoformat(),
        "model_version": MODEL_VERSION,
    }
    for key, value in fields.items():
        if key.lower() in _SECRET_KEYS:
            continue
        row[key] = str(value)
    if _on():
        _logs.append(row)
    return row


def start_span(name: str, request_id: str) -> str:
    span_id = f"{name}:{len(_spans)}"
    if _on():
        _spans.append({"id": span_id, "name": name, "request_id": request_id or _MISSING, "status": "open"})
        setup_otel()
        from app.services.ops_observe.otel import start_otel_span

        otel_span = start_otel_span(name, request_id)
        otel_span.end()
    return span_id


def p95(samples: list[float]) -> str:
    """Nearest-rank percentile. Empty input stays unset."""
    if not samples:
        return _MISSING
    ordered = sorted(samples)
    rank = math.ceil(0.95 * len(ordered))
    index = min(len(ordered), max(1, rank)) - 1
    return format(Decimal(str(ordered[index])), "f")


def slo_status() -> dict[str, str]:
    cfg = _cfg()
    api = p95(_latency_ms)
    report = p95(_report_seconds)
    api_limit = Decimal(str(cfg["api_p95_ms"]))
    report_limit = Decimal(str(cfg["report_seconds"]))
    return {
        "api_p95_ms": api,
        "api": _MISSING if api == _MISSING else ("ok" if Decimal(api) <= api_limit else "breach"),
        "report_seconds": report,
        "report": _MISSING if report == _MISSING else ("ok" if Decimal(report) <= report_limit else "breach"),
        "sync_timeout_seconds": _MISSING if cfg.get("sync_timeout_seconds") in (None, "") else str(cfg["sync_timeout_seconds"]),
        "availability": _MISSING if cfg.get("availability_target") in (None, "") else str(cfg["availability_target"]),
        "errors": str(len(_errors)),
        "backup": _MISSING,
        "infra_payment": _MISSING,
    }


def admin_view() -> dict[str, Any]:
    if not _on():
        return {"status": "off"}
    setup_otel()
    flags = snapshot().get("global", {})
    return {
        "status": "on",
        "model_version": MODEL_VERSION,
        "slo": slo_status(),
        "alerts": [row["name"] for row in _alerts],
        "shadow_diffs": str(_shadow),
        "backup": _MISSING,
        "infra_payment": _MISSING,
        "live": bool(flags.get("qa_act_live")),
        "partners": bool(flags.get("qa_partners")),
        "logs": len(_logs),
        "otel": {
            "sdk": "on",
            "exporter": otlp_endpoint() or "in_memory",
            "spans": recorded_span_names()[-20:],
            "instrumentation": ["fastapi", "sqlalchemy", "celery", "redis", "httpx", "grpc"],
        },
    }


def drill(name: str) -> dict[str, str]:
    if name not in _DRILLS:
        raise KeyError(name)
    text = (_RUNBOOKS / f"{name}.md").read_text(encoding="utf-8")
    if "## Шаги" not in text or "## Проверка" not in text:
        raise ValueError(name)
    service = _DRILLS[name]
    alert = note_failure(service, "drill")
    view = read_degraded(service, failed=True)
    return {"runbook": name, "alert": alert["name"], "value": view["value"], "mark": view["mark"], "status": view["status"]}
