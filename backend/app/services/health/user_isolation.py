"""Cross-user isolation probes for hourly health reporter."""
from __future__ import annotations

import json
import os
from typing import Any

import httpx
import websockets

from app.core.logging import get_logger
from app.services.health.reporter import (
    _base_url,
    _is_auth_failure,
    _resolve_user_token,
    _row,
)

logger = get_logger(__name__)

_OPEN_PARAMS = {"status": "approved,filled,executing", "page_size": 100}
_CLOSED_PARAMS = {"status": "closed", "page_size": 100}
_PENDING_PARAMS = {"status": "pending,pending_approval,awaiting_approval", "page_size": 100}


def _maneuver_ids(payload: dict[str, Any]) -> set[str]:
    items = payload.get("items") or []
    return {str(m.get("id")) for m in items if m.get("id")}


def _maneuver_tickers(payload: dict[str, Any]) -> set[str]:
    items = payload.get("items") or []
    return {str(m.get("ticker")).upper() for m in items if m.get("ticker")}


def _order_ids(payload: list | dict) -> set[str]:
    rows = payload if isinstance(payload, list) else payload.get("items") or []
    return {str(o.get("id")) for o in rows if o.get("id")}


async def _get_json(
    client: httpx.AsyncClient,
    path: str,
    *,
    token: str,
    params: dict | None = None,
) -> Any:
    headers = {"Authorization": f"Bearer {token}"}
    r = await client.get(f"{_base_url()}{path}", headers=headers, params=params)
    r.raise_for_status()
    return r.json()


async def _fetch_user_surface(
    user: str,
    token: str,
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            return {
                "positions_alias": await _get_json(client, "/api/positions", token=token, params=_OPEN_PARAMS),
                "maneuvers_open": await _get_json(
                    client, "/api/v1/maneuvers", token=token, params=_OPEN_PARAMS
                ),
                "maneuvers_closed": await _get_json(
                    client, "/api/v1/maneuvers", token=token, params=_CLOSED_PARAMS
                ),
                "maneuvers_pending": await _get_json(
                    client, "/api/v1/maneuvers", token=token, params=_PENDING_PARAMS
                ),
                "portfolio_metrics": await _get_json(client, "/api/v1/portfolio/metrics", token=token),
                "orders": await _get_json(client, "/api/v1/orders", token=token),
                "account": await _get_json(client, "/api/v1/account", token=token),
                "grid": await _get_json(client, "/api/v1/grid", token=token),
            }
        except Exception as exc:
            if not _is_auth_failure(exc):
                raise
            logger.info("health_isolation_token_stale_relogin", user=user)
            fresh = await _resolve_user_token(user, force_login=True)
            if not fresh:
                raise
            return await _fetch_user_surface(user, fresh)


async def _ws_positions_snapshot(token: str) -> dict[str, Any]:
    ws_base = _base_url().replace("https://", "wss://").replace("http://", "ws://")
    url = f"{ws_base}/api/v1/ws/positions?token={token}"
    async with websockets.connect(url, open_timeout=15, close_timeout=5) as ws:
        for _ in range(12):
            raw = await ws.recv()
            msg = json.loads(raw)
            if msg.get("type") == "positions_snapshot":
                return msg.get("data") or {}
    raise TimeoutError("positions_snapshot not received within 12 messages")


async def check_cross_user_data_isolation() -> dict[str, Any]:
    """Probe every user-scoped financial surface for cross-account overlap."""
    token_a = await _resolve_user_token("A")
    token_b = await _resolve_user_token("B")
    if not token_a or not token_b:
        return _row(
            "cross_user_data_isolation",
            "skipped",
            "TEST_USER_A/B_TOKEN or EMAIL/PASSWORD not set",
        )

    try:
        surface_a = await _fetch_user_surface("A", token_a)
        surface_b = await _fetch_user_surface("B", token_b)
    except Exception as exc:
        return _row("cross_user_data_isolation", "failed", str(exc)[:800])

    failures: list[str] = []

    def _assert_disjoint(label: str, left: set[str], right: set[str]) -> None:
        overlap = left & right
        if overlap:
            failures.append(f"{label}: {sorted(overlap)[:5]}")

    _assert_disjoint(
        "positions_alias",
        _maneuver_ids(surface_a["positions_alias"]),
        _maneuver_ids(surface_b["positions_alias"]),
    )
    _assert_disjoint(
        "maneuvers_open",
        _maneuver_ids(surface_a["maneuvers_open"]),
        _maneuver_ids(surface_b["maneuvers_open"]),
    )
    _assert_disjoint(
        "maneuvers_closed",
        _maneuver_ids(surface_a["maneuvers_closed"]),
        _maneuver_ids(surface_b["maneuvers_closed"]),
    )
    _assert_disjoint(
        "maneuvers_pending",
        _maneuver_ids(surface_a["maneuvers_pending"]),
        _maneuver_ids(surface_b["maneuvers_pending"]),
    )
    _assert_disjoint(
        "orders",
        _order_ids(surface_a["orders"]),
        _order_ids(surface_b["orders"]),
    )

    grid_a = surface_a["grid"] if isinstance(surface_a["grid"], list) else surface_a["grid"].get("items") or []
    grid_b = surface_b["grid"] if isinstance(surface_b["grid"], list) else surface_b["grid"].get("items") or []
    _assert_disjoint(
        "grid_bots",
        {str(g.get("bot_id")) for g in grid_a if g.get("bot_id")},
        {str(g.get("bot_id")) for g in grid_b if g.get("bot_id")},
    )

    metrics_a = surface_a["portfolio_metrics"]
    metrics_b = surface_b["portfolio_metrics"]
    open_a = int(metrics_a.get("open_maneuvers") or 0)
    open_b = int(metrics_b.get("open_maneuvers") or 0)
    ids_a = _maneuver_ids(surface_a["maneuvers_open"])
    ids_b = _maneuver_ids(surface_b["maneuvers_open"])
    if open_a != len(ids_a):
        failures.append(f"metrics_open_count_mismatch_A: metrics={open_a} list={len(ids_a)}")
    if open_b != len(ids_b):
        failures.append(f"metrics_open_count_mismatch_B: metrics={open_b} list={len(ids_b)}")

    try:
        ws_a = await _ws_positions_snapshot(token_a)
        ws_ids_a = _maneuver_ids(ws_a)
        rest_ids_a = _maneuver_ids(surface_a["maneuvers_open"])
        if ws_ids_a != rest_ids_a:
            failures.append(
                f"ws_rest_mismatch_A: ws={sorted(ws_ids_a)[:3]} rest={sorted(rest_ids_a)[:3]}"
            )
    except Exception as exc:
        failures.append(f"ws_positions_A: {str(exc)[:120]}")

    if failures:
        return _row("cross_user_data_isolation", "failed", "; ".join(failures))

    return _row(
        "cross_user_data_isolation",
        "passed",
        detail=f"A tickers={sorted(_maneuver_tickers(surface_a['maneuvers_open']))[:5]} "
        f"B tickers={sorted(_maneuver_tickers(surface_b['maneuvers_open']))[:5]}",
    )


async def check_cross_user_position_isolation() -> dict[str, Any]:
    """Backward-compatible alias used by legacy health reporter name."""
    result = await check_cross_user_data_isolation()
    result["name"] = "cross_user_position_isolation"
    return result
