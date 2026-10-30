"""T-Bank adapter surface (Prompt 06). Platform token ≠ user token."""
from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.services.venue_adapters.errors import ReadOnlyTradeBlocked
from app.services.venue_adapters.key_check import inspect_key_permissions
from app.services.venue_adapters.normalize import ingest_operations

PROD_HOST = "invest-public-api.tbank.ru:443"
SANDBOX_HOST = "sandbox-invest-public-api.tbank.ru:443"


def grpc_metadata(*, user_token: str | None = None) -> list[tuple[str, str]]:
    """x-app-name stays QuantAnalytics. User token is never mixed with platform token."""
    meta = [("x-app-name", settings.TINKOFF_APP_NAME)]
    if user_token:
        meta.append(("authorization", f"Bearer {user_token}"))
    return meta


def host(*, sandbox: bool) -> str:
    return SANDBOX_HOST if sandbox else PROD_HOST


def connect_preview(
    *,
    user_id: str,
    scopes: list[str],
    operations: list[dict[str, Any]],
    readonly: bool = False,
    sandbox: bool = True,
) -> dict[str, Any]:
    from app.services.ops_observe.otel import tracer

    with tracer().start_as_current_span("tbank.grpc") as span:
        span.set_attribute("rpc.system", "grpc")
        span.set_attribute("server.address", host(sandbox=sandbox))
        inspect_key_permissions("tbank", scopes)
    if readonly:
        trade_ok = False
    else:
        trade_ok = "trade" in {s.lower() for s in scopes} or "orders" in {s.lower() for s in scopes}
    book_mode = "paper" if sandbox else "live"
    ingested = ingest_operations(user_id=user_id, venue="tbank", mode=book_mode, operations=operations)
    return {
        "venue": "tbank",
        "host": host(sandbox=sandbox),
        "app_name": settings.TINKOFF_APP_NAME,
        "sandbox": sandbox,
        "trade_enabled": False,
        "trade_available": trade_ok,
        "readonly": readonly,
        "accounts": [{"id": ingested["account_id"], "mode": book_mode}],
        "coverage_from": ingested["coverage_from"],
        "synced": ingested["accepted"],
        "trade_block": None if trade_ok else ReadOnlyTradeBlocked().message,
    }


def isolate_tokens(platform_token: str, user_a: str, user_b: str) -> None:
    if platform_token and platform_token in {user_a, user_b}:
        raise ValueError("platform token must not equal a user token")
    if user_a == user_b:
        raise ValueError("user tokens must be distinct")
