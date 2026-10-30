"""
WebSocket endpoints for real-time updates.

Channels:
  /ws/pipeline  — pipeline run status + new report notifications
  /ws/prices    — live price ticker (polls market data, broadcasts to subscribers)
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from app.core.logging import get_logger
from app.core.security import JWTError, decode_token

logger = get_logger(__name__)
router = APIRouter(prefix="/ws", tags=["websocket"])
_WS_ERR = "нет данных"

# Per-quote timeout so a hung broker call cannot freeze the whole pulse loop.
_QUOTE_TIMEOUT_SEC = 8.0
_PULSE_LOOP_TIMEOUT_SEC = 35.0
# Cap concurrent WS snapshot DB sessions so REST/auth never starve the pool.
_WS_POSITIONS_DB_SLOTS = 8
_ws_positions_db_semaphore = asyncio.Semaphore(_WS_POSITIONS_DB_SLOTS)


# ── Connection manager ────────────────────────────────────────────────────────

class ConnectionManager:
    """Manages active WebSocket connections per channel."""

    def __init__(self) -> None:
        self._channels: dict[str, set[WebSocket]] = {}

    async def connect(self, ws: WebSocket, channel: str) -> None:
        await ws.accept()
        self._channels.setdefault(channel, set()).add(ws)
        logger.debug("WS connected", channel=channel, total=len(self._channels[channel]))

    def disconnect(self, ws: WebSocket, channel: str) -> None:
        self._channels.get(channel, set()).discard(ws)
        logger.debug("WS disconnected", channel=channel)

    async def broadcast(self, channel: str, payload: dict) -> None:
        """Send a message to all subscribers of a channel."""
        dead: list[WebSocket] = []
        for ws in list(self._channels.get(channel, set())):
            try:
                await ws.send_text(json.dumps(payload, default=str))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws, channel)

    async def send(self, ws: WebSocket, payload: dict) -> None:
        try:
            await ws.send_text(json.dumps(payload, default=str))
        except Exception as exc:
            logger.debug("ws_send_failed", error=str(exc), msg_type=payload.get("type"))

    def subscriber_count(self, channel: str) -> int:
        return len(self._channels.get(channel, set()))


manager = ConnectionManager()


def pipeline_ws_channel(email: str) -> str:
    return f"pipeline:{email.strip().lower()}"


def owner_email_for_pipeline_payload(payload: dict[str, Any]) -> str | None:
    raw = payload.get("owner_email") or payload.get("email")
    if isinstance(raw, str) and "@" in raw:
        return raw.strip().lower()
    triggered = str(payload.get("triggered_by") or "").strip()
    if not triggered:
        return None
    candidate = triggered.split(":", 1)[-1].strip().lower() if ":" in triggered else triggered.lower()
    if "@" in candidate:
        return candidate
    return None


def may_watch_pipeline_run(meta: dict[str, Any] | None, *, email: str, user_id: str) -> bool:
    from app.api.v1.endpoints.pipeline import _pipeline_run_owned

    return _pipeline_run_owned(meta, email=email, user_id=user_id)


# ── Auth helper ───────────────────────────────────────────────────────────────

async def _authenticate_ws(token: str) -> str | None:
    """Validate a JWT passed as query param. Returns email or None."""
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            return None
        email = payload.get("sub")
        if not isinstance(email, str) or not email:
            return None
        from app.db.session import AsyncSessionLocal
        from app.services.auth.user_verification import user_needs_verification
        from app.services.portfolio.user_scope import get_user_by_email

        try:
            async with AsyncSessionLocal() as session:
                user = await get_user_by_email(session, email)
                if user is None or not bool(getattr(user, "is_active", True)):
                    return None
                if user_needs_verification(user):
                    return None
        except Exception as exc:  # noqa: BLE001 — fail closed
            logger.warning("ws_auth_user_lookup_failed", error=str(exc)[:200])
            return None
        return email
    except JWTError:
        return None


# ── Pipeline status channel ────────────────────────────────────────────────────

@router.websocket("/pipeline")
async def ws_pipeline(
    ws: WebSocket,
    token: str = Query(..., description="JWT access token"),
) -> None:
    """
    Real-time pipeline updates.

    Messages sent to client:
      {"type": "connected", "message": "..."}
      {"type": "pipeline_queued",   "run_id": "..."}
      {"type": "pipeline_complete", "run_id": "...", "report_id": "..."}
      {"type": "pipeline_failed",   "run_id": "...", "error": "..."}
      {"type": "maneuver_approved", "maneuver_id": "..."}
      {"type": "heartbeat",         "ts": "..."}

    Messages received from client:
      {"action": "subscribe_run", "run_id": "..."}
    """
    email = await _authenticate_ws(token)
    if not email:
        await ws.close(code=4001, reason="Unauthorized")
        return

    channel = pipeline_ws_channel(email)
    await manager.connect(ws, channel)
    await manager.send(ws, {
        "type": "connected",
        "message": f"Subscribed to pipeline updates",
        "ts": datetime.now(timezone.utc).isoformat(),
    })

    heartbeat_task = asyncio.create_task(_heartbeat(ws, interval=30))

    try:
        while True:
            try:
                raw = await asyncio.wait_for(ws.receive_text(), timeout=60.0)
                msg = json.loads(raw)
                action = msg.get("action")

                if action == "subscribe_run":
                    run_id = msg.get("run_id")
                    if run_id:
                        from app.db.session import AsyncSessionLocal
                        from app.services.portfolio.user_scope import get_user_by_email
                        from app.utils.pipeline_tracker import get_run

                        user_id = ""
                        try:
                            async with AsyncSessionLocal() as session:
                                user = await get_user_by_email(session, email)
                                user_id = str(getattr(user, "id", "") or "")
                        except Exception as exc:  # noqa: BLE001
                            logger.warning("ws_pipeline_user_lookup_failed", error=str(exc)[:200])
                        meta = get_run(str(run_id))
                        if not may_watch_pipeline_run(meta, email=email, user_id=user_id):
                            await manager.send(ws, {"type": "error", "message": "нет данных"})
                        else:
                            asyncio.create_task(_poll_run_status(ws, run_id))

                elif action == "ping":
                    await manager.send(ws, {"type": "pong", "ts": datetime.now(timezone.utc).isoformat()})

            except asyncio.TimeoutError:
                # Send heartbeat to keep connection alive
                await manager.send(ws, {"type": "heartbeat", "ts": datetime.now(timezone.utc).isoformat()})
            except json.JSONDecodeError:
                await manager.send(ws, {"type": "error", "message": "Invalid JSON"})

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning("WS pipeline error", error=str(exc))
    finally:
        heartbeat_task.cancel()
        manager.disconnect(ws, channel)


async def _poll_run_status(ws: WebSocket, run_id: str) -> None:
    """Poll Celery for a specific run and push status updates."""
    try:
        from celery.result import AsyncResult
        for _ in range(60):  # max 3 minutes (60 × 3s)
            result = AsyncResult(run_id)
            if result.state == "SUCCESS":
                report_id = (result.result or {}).get("report_id")
                await manager.send(ws, {
                    "type": "pipeline_complete",
                    "run_id": run_id,
                    "report_id": report_id,
                    "ts": datetime.now(timezone.utc).isoformat(),
                })
                return
            elif result.state == "FAILURE":
                await manager.send(ws, {
                    "type": "pipeline_failed",
                    "run_id": run_id,
                    "error": "нет данных",
                    "ts": datetime.now(timezone.utc).isoformat(),
                })
                return
            else:
                await manager.send(ws, {
                    "type": "pipeline_progress",
                    "run_id": run_id,
                    "state": result.state,
                    "ts": datetime.now(timezone.utc).isoformat(),
                })
            await asyncio.sleep(3)
    except Exception as exc:
        logger.warning("Run status poll failed", run_id=run_id, error=str(exc))


# ── Prices channel ────────────────────────────────────────────────────────────

@router.websocket("/prices")
async def ws_prices(
    ws: WebSocket,
    token: str = Query(...),
    tickers: str = Query("SPY,QQQ,AAPL", description="Comma-separated tickers"),
) -> None:
    """
    Live price feed (polls market data every 5 seconds).

    Messages:
      {"type": "prices", "data": {"AAPL": {"price": 182.5, ...}, ...}, "ts": "..."}
      {"type": "error",  "message": "..."}
    """
    email = await _authenticate_ws(token)
    if not email:
        await ws.close(code=4001, reason="Unauthorized")
        return

    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()][:20]
    channel = f"prices:{'_'.join(sorted(ticker_list))}"
    await manager.connect(ws, channel)
    await manager.send(ws, {
        "type": "subscribed",
        "tickers": ticker_list,
        "interval_seconds": 5,
    })

    heartbeat_task = asyncio.create_task(_heartbeat(ws, interval=30))
    price_task = asyncio.create_task(_price_broadcaster(ws, ticker_list))

    try:
        while True:
            try:
                raw = await asyncio.wait_for(ws.receive_text(), timeout=120.0)
                msg = json.loads(raw)
                if msg.get("action") == "change_tickers":
                    new_tickers = msg.get("tickers", [])
                    if new_tickers:
                        price_task.cancel()
                        ticker_list = [t.upper() for t in new_tickers[:20]]
                        price_task = asyncio.create_task(
                            _price_broadcaster(ws, ticker_list)
                        )
            except asyncio.TimeoutError:
                pass
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning("WS prices error", error=str(exc))
    finally:
        heartbeat_task.cancel()
        price_task.cancel()
        manager.disconnect(ws, channel)


async def _price_broadcaster(ws: WebSocket, tickers: list[str]) -> None:
    """Continuously fetch quotes and push to client — one in-flight per ticker set."""
    from app.services.market_data.client import get_market_data_client
    from app.services.market_data.license import stamp_quote
    from app.services.market_data.quote_hub import hub

    client = get_market_data_client()

    async def _fetch(symbols: list[str]) -> dict:
        return await client.get_multiple_quotes(symbols)

    while True:
        try:
            raw = await hub.fetch_many(tickers, _fetch)
            quotes = {
                sym: stamp_quote(dict(payload) if isinstance(payload, dict) else {"price": payload, "symbol": sym})
                for sym, payload in raw.items()
            }
            await manager.send(ws, {
                "type": "prices",
                "data": quotes,
                "ts": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as exc:
            logger.warning("ws price fetch failed", error=str(exc)[:200])
            await manager.send(ws, {"type": "error", "message": _WS_ERR})
        await asyncio.sleep(5)


# ── Portfolio metrics channel (NavBar TRD/BLNC/SUM) ───────────────────────────

@router.websocket("/portfolio")
async def ws_portfolio(
    ws: WebSocket,
    token: str = Query(...),
) -> None:
    """
    Live portfolio capital metrics (same payload as GET /portfolio/metrics).

    Messages:
      {"type": "portfolio_metrics", "data": {...}, "ts": "..."}
      {"type": "subscribed", "email": "..."}
    """
    email = await _authenticate_ws(token)
    if not email:
        await ws.close(code=4001, reason="Unauthorized")
        return

    channel = f"portfolio:{email.lower()}"
    await manager.connect(ws, channel)
    await manager.send(ws, {"type": "subscribed", "email": email})

    heartbeat_task = asyncio.create_task(_heartbeat(ws, interval=30))
    metrics_task = asyncio.create_task(_portfolio_broadcaster(ws, email))

    try:
        while True:
            try:
                raw = await asyncio.wait_for(ws.receive_text(), timeout=120.0)
                msg = json.loads(raw)
                if msg.get("action") == "ping":
                    await manager.send(ws, {"type": "pong", "ts": datetime.now(timezone.utc).isoformat()})
            except asyncio.TimeoutError:
                pass
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning("WS portfolio error", error=str(exc))
    finally:
        heartbeat_task.cancel()
        metrics_task.cancel()
        manager.disconnect(ws, channel)


async def _portfolio_broadcaster(ws: WebSocket, email: str) -> None:
    """Recalculate paper/live metrics on the same cadence as /ws/prices."""
    from app.db.rls import set_session_user_id
    from app.db.session import AsyncSessionLocal
    from app.services.portfolio.metrics import build_portfolio_metrics
    from app.services.portfolio.user_scope import get_user_by_email

    session_user_id: str | None = None
    async with AsyncSessionLocal() as lookup_db:
        user = await get_user_by_email(lookup_db, email)
        session_user_id = user.id if user else None

    while True:
        try:
            async with AsyncSessionLocal() as db:
                await set_session_user_id(db, session_user_id)
                metrics = await asyncio.wait_for(
                    build_portfolio_metrics(email, db),
                    timeout=_PULSE_LOOP_TIMEOUT_SEC,
                )
            await manager.send(
                ws,
                {
                    "type": "portfolio_metrics",
                    "data": metrics.model_dump(),
                    "ts": datetime.now(timezone.utc).isoformat(),
                },
            )
            logger.debug(
                "ws_portfolio_tick",
                email=email,
                total_usd=metrics.total_usd,
                unrealized=metrics.unrealized_pnl_usd,
            )
        except asyncio.TimeoutError:
            logger.warning("ws_portfolio_pulse_timeout", email=email)
            await manager.send(ws, {"type": "error", "message": "Portfolio metrics timed out"})
        except Exception as exc:
            logger.warning("ws_portfolio_pulse_failed", email=email, error=str(exc))
            logger.warning("ws portfolio metrics failed", error=str(exc)[:200])
            await manager.send(ws, {"type": "error", "message": _WS_ERR})
        await asyncio.sleep(15)


# ── Open positions channel (BottomStrip / positions tab) ─────────────────────

@router.websocket("/positions")
async def ws_positions(
    ws: WebSocket,
    token: str = Query(...),
) -> None:
    """
    Live open-positions snapshot (~5s cadence).

    Messages:
      {"type": "positions_snapshot", "data": {...}, "ts": "..."}
      {"type": "subscribed", "email": "..."}
    """
    email = await _authenticate_ws(token)
    if not email:
        await ws.close(code=4001, reason="Unauthorized")
        return

    channel = f"positions:{email.lower()}"
    await manager.connect(ws, channel)
    await manager.send(ws, {"type": "subscribed", "email": email})

    heartbeat_task = asyncio.create_task(_heartbeat(ws, interval=30))
    positions_task = asyncio.create_task(_positions_broadcaster(ws, email))

    try:
        while True:
            try:
                raw = await asyncio.wait_for(ws.receive_text(), timeout=120.0)
                msg = json.loads(raw)
                if msg.get("action") == "ping":
                    await manager.send(ws, {"type": "pong", "ts": datetime.now(timezone.utc).isoformat()})
            except asyncio.TimeoutError:
                pass
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning("WS positions error", error=str(exc))
    finally:
        heartbeat_task.cancel()
        positions_task.cancel()
        manager.disconnect(ws, channel)


async def _positions_broadcaster(ws: WebSocket, email: str) -> None:
    from app.db.rls import set_session_user_id
    from app.db.session import AsyncSessionLocal
    from app.services.portfolio.positions_snapshot import build_open_positions_snapshot
    from app.services.portfolio.user_scope import get_user_by_email

    session_user_id: str | None = None
    async with AsyncSessionLocal() as lookup_db:
        user = await get_user_by_email(lookup_db, email)
        session_user_id = user.id if user else None

    while True:
        try:
            async with _ws_positions_db_semaphore:
                async with AsyncSessionLocal() as db:
                    await set_session_user_id(db, session_user_id)
                    snapshot = await asyncio.wait_for(
                        build_open_positions_snapshot(email, db),
                        timeout=_PULSE_LOOP_TIMEOUT_SEC,
                    )
            await manager.send(
                ws,
                {
                    "type": "positions_snapshot",
                    "data": snapshot,
                    "ts": datetime.now(timezone.utc).isoformat(),
                },
            )
            logger.debug(
                "ws_positions_tick",
                email=email,
                count=snapshot.get("total", 0),
                stale=(snapshot.get("live_snapshot") or {}).get("stale"),
            )
        except asyncio.TimeoutError:
            logger.warning("ws_positions_pulse_timeout", email=email)
            await manager.send(ws, {"type": "error", "message": "Positions snapshot timed out"})
        except Exception as exc:
            logger.warning("ws_positions_pulse_failed", email=email, error=str(exc))
            logger.warning("ws positions snapshot failed", error=str(exc)[:200])
            await manager.send(ws, {"type": "error", "message": _WS_ERR})
        await asyncio.sleep(5)


async def _heartbeat(ws: WebSocket, interval: int = 30) -> None:
    """Send periodic heartbeat to keep the connection alive."""
    while True:
        await asyncio.sleep(interval)
        try:
            await ws.send_text(json.dumps({
                "type": "heartbeat",
                "ts": datetime.now(timezone.utc).isoformat(),
            }))
        except Exception:
            break


# ── Terminal channel (heartbeat + lightweight quote pulse) ────────────────────

@router.websocket("/terminal")
async def ws_terminal(
    ws: WebSocket,
    token: Optional[str] = Query(None, description="Optional JWT access token"),
    symbols: str = Query(
        "BTC-USD,ETH-USD,AAPL,MSFT,^GSPC,^DJI,^IXIC,^VIX,IMOEX.ME",
        description="Comma-separated symbols for pulse quotes",
    ),
) -> None:
    """
    Lightweight QuantAnalytics Terminal feed.

    Auth is optional (public market read, same as /terminal/quote).
    When a token is provided it must be a valid access JWT.

    Messages:
      {"type": "connected"|"heartbeat"|"ping", "ts": "..."}
      {"type": "tick", "data": {"watchlist": [...], "indices": [...]}, "ts": "..."}

    Tick payloads are sparse patches: empty panels are omitted so clients
    must merge by symbol and must not wipe last-good snapshot rows.
    """
    if token:
        email = await _authenticate_ws(token)
        if not email:
            await ws.close(code=4001, reason="Unauthorized")
            return

    ticker_list = [t.strip() for t in symbols.split(",") if t.strip()][:12]
    channel = "terminal"
    await manager.connect(ws, channel)
    await manager.send(
        ws,
        {
            "type": "connected",
            "message": "Subscribed to terminal updates",
            "symbols": ticker_list,
            "ts": datetime.now(timezone.utc).isoformat(),
        },
    )

    heartbeat_task = asyncio.create_task(_heartbeat(ws, interval=25))
    pulse_task = asyncio.create_task(_terminal_pulse_broadcaster(ws, ticker_list))

    try:
        while True:
            try:
                raw = await asyncio.wait_for(ws.receive_text(), timeout=120.0)
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                action = msg.get("action") or msg.get("type")
                if action in {"ping", "heartbeat"}:
                    await manager.send(
                        ws,
                        {"type": "pong", "ts": datetime.now(timezone.utc).isoformat()},
                    )
                elif action == "change_symbols":
                    new_syms = msg.get("symbols") or []
                    if isinstance(new_syms, list) and new_syms:
                        pulse_task.cancel()
                        ticker_list = [str(s).strip() for s in new_syms if str(s).strip()][:12]
                        pulse_task = asyncio.create_task(
                            _terminal_pulse_broadcaster(ws, ticker_list)
                        )
            except asyncio.TimeoutError:
                pass
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning("WS terminal error", error=str(exc))
    finally:
        heartbeat_task.cancel()
        pulse_task.cancel()
        manager.disconnect(ws, channel)


async def _terminal_pulse_broadcaster(ws: WebSocket, symbols: list[str]) -> None:
    """Push compact watchlist/indices/tape ticks every ~15s via ProviderRouter."""
    from app.services.terminal_platform.factory import get_terminal_router
    from app.services.terminal_platform.market.hours import build_market_hours

    index_map = {
        "^GSPC": "SPX",
        "^IXIC": "IXIC",
        "^NDX": "NDX",
        "^DJI": "DJI",
        "^VIX": "VIX",
        "^GDAXI": "DAX",
        "^N225": "N225",
        "IMOEX.ME": "IMOEX",
        "IMOEX": "IMOEX",
    }

    async def _fetch_one(sym: str) -> tuple[str, Any | None]:
        router_tp = get_terminal_router()
        try:
            result = await asyncio.wait_for(router_tp.get_quote(sym), timeout=_QUOTE_TIMEOUT_SEC)
        except asyncio.TimeoutError:
            logger.warning("ws_terminal_quote_timeout", symbol=sym)
            return sym, None
        except Exception as exc:
            logger.warning("ws_terminal_quote_failed", symbol=sym, error=str(exc))
            return sym, None
        if not result.success or result.data is None:
            return sym, None
        return sym, result.data

    while True:
        try:
            quote_results = await asyncio.gather(*(_fetch_one(sym) for sym in symbols))
            watchlist: list[dict[str, Any]] = []
            indices: list[dict[str, Any]] = []
            tape: list[dict[str, Any]] = []
            for sym, q in quote_results:
                if q is None:
                    continue
                price_raw = getattr(q, "price", None)
                try:
                    price = float(price_raw) if price_raw is not None else None
                except (TypeError, ValueError):
                    price = None
                if price is None:
                    continue
                change_pct = getattr(q, "change_pct", None)
                change_pct_f = float(change_pct) if change_pct is not None else None
                change = (
                    round(price * change_pct_f / 100.0, 6) if change_pct_f is not None else None
                )
                if sym in index_map:
                    ui = index_map[sym]
                    idx_row: dict[str, Any] = {"symbol": ui, "price": price}
                    if change is not None:
                        idx_row["change"] = change
                    if change_pct_f is not None:
                        idx_row["change_pct"] = change_pct_f
                    indices.append(idx_row)
                    chg_txt = f"{change_pct_f:+.2f}%" if change_pct_f is not None else "n/a"
                    tape_row: dict[str, Any] = {
                        "kind": "quote",
                        "symbol": ui,
                        "text": f"{ui} {price:.2f} ({chg_txt})",
                        "price": price,
                    }
                    if change_pct_f is not None:
                        tape_row["change_pct"] = change_pct_f
                    tape.append(tape_row)
                else:
                    label = sym.replace("-USD", "/USDT") if "-USD" in sym else sym
                    w_row: dict[str, Any] = {"symbol": label, "last": price}
                    if change_pct_f is not None:
                        w_row["change_pct"] = change_pct_f
                    watchlist.append(w_row)
                    chg_txt = f"{change_pct_f:+.2f}%" if change_pct_f is not None else "n/a"
                    tape_row = {
                        "kind": "quote",
                        "symbol": label,
                        "text": f"{label} {price:.2f} ({chg_txt})",
                        "price": price,
                    }
                    if change_pct_f is not None:
                        tape_row["change_pct"] = change_pct_f
                    tape.append(tape_row)

            try:
                for h in build_market_hours()[:4]:
                    tape.append(
                        {
                            "kind": "hours",
                            "symbol": h.exchange,
                            "text": f"{h.exchange} {h.status}",
                        }
                    )
            except Exception:
                raise

            patch: dict[str, Any] = {}
            if indices:
                patch["indices"] = indices
            if watchlist:
                patch["watchlist"] = watchlist
            if tape:
                patch["tape_items"] = tape
            if patch:
                await manager.send(
                    ws,
                    {
                        "type": "tick",
                        "data": patch,
                        "ts": datetime.now(timezone.utc).isoformat(),
                    },
                )
                logger.debug(
                    "ws_terminal_tick",
                    symbols=len(symbols),
                    quotes=len(watchlist) + len(indices),
                )
            else:
                logger.warning("ws_terminal_tick_empty", symbols=symbols)
        except Exception as exc:
            logger.warning("ws_terminal_pulse_failed", error=str(exc)[:200])
            await manager.send(
                ws,
                {"type": "error", "message": _WS_ERR},
            )
        await asyncio.sleep(15)


# ── Broadcast helpers (called from Celery tasks) ──────────────────────────────

async def notify_pipeline_event(event_type: str, payload: dict) -> None:
    """Send a pipeline event only to the run owner's channel."""
    email = owner_email_for_pipeline_payload(payload)
    if not email:
        logger.warning("pipeline ws skip — no owner")
        return
    await manager.broadcast(pipeline_ws_channel(email), {"type": event_type, **payload})


async def notify_cockpit_event(symbol: str, payload: dict) -> None:
    channel = f"cockpit:{symbol.upper()}"
    await manager.broadcast(channel, {"type": "cockpit_update", "symbol": symbol.upper(), **payload})


async def notify_chat_event(conversation_id: str, payload: dict) -> None:
    channel = f"chat:{conversation_id}"
    await manager.broadcast(channel, {"type": "chat_message", **payload})


async def notify_portfolio_metrics(email: str, payload: dict) -> None:
    """Push refreshed NavBar metrics to portfolio WS subscribers."""
    channel = f"portfolio:{email.lower()}"
    await manager.broadcast(channel, {"type": "portfolio_metrics", **payload})


# ── Cockpit channel (price + forecast push) ─────────────────────────────────────

@router.websocket("/cockpit")
async def ws_cockpit(
    ws: WebSocket,
    token: str = Query(...),
    symbol: str = Query(..., description="Ticker symbol"),
) -> None:
    """Live cockpit updates for a single symbol with polling fallback on client."""
    email = await _authenticate_ws(token)
    if not email:
        await ws.close(code=4001, reason="Unauthorized")
        return

    sym = symbol.strip().upper()
    channel = f"cockpit:{sym}"
    await manager.connect(ws, channel)
    await manager.send(ws, {"type": "subscribed", "symbol": sym})

    heartbeat_task = asyncio.create_task(_heartbeat(ws, interval=30))
    push_task = asyncio.create_task(_cockpit_broadcaster(ws, sym))

    try:
        while True:
            try:
                raw = await asyncio.wait_for(ws.receive_text(), timeout=120.0)
                msg = json.loads(raw)
                if msg.get("action") == "ping":
                    await manager.send(ws, {"type": "pong", "ts": datetime.now(timezone.utc).isoformat()})
            except asyncio.TimeoutError:
                pass
    except WebSocketDisconnect:
        pass
    finally:
        heartbeat_task.cancel()
        push_task.cancel()
        manager.disconnect(ws, channel)


async def _cockpit_broadcaster(ws: WebSocket, symbol: str) -> None:
    from app.services.market_data.client import get_market_data_client

    client = get_market_data_client()
    while True:
        try:
            quotes = await client.get_multiple_quotes([symbol])
            quote = quotes.get(symbol, {})
            from app.services.market_data.license import stamp_quote

            tagged = stamp_quote(dict(quote) if isinstance(quote, dict) else {"price": quote, "symbol": symbol})
            await manager.send(
                ws,
                {
                    "type": "price",
                    "symbol": symbol,
                    "data": tagged,
                    "ts": datetime.now(timezone.utc).isoformat(),
                },
            )
        except Exception as exc:
            logger.warning("ws cockpit price failed", error=str(exc)[:200])
            await manager.send(ws, {"type": "error", "message": _WS_ERR})
        await asyncio.sleep(5)


# ── Chat channel ──────────────────────────────────────────────────────────────

@router.websocket("/chat/{conversation_id}")
async def ws_chat(
    ws: WebSocket,
    conversation_id: str,
    token: str = Query(...),
) -> None:
    """Real-time chat delivery for an authorized conversation."""
    from app.core.deps import get_db as _get_db_dep
    from app.core.rbac_deps import get_identity_for_email, get_user_and_role
    from app.db.session import AsyncSessionLocal
    from app.services.chat.service import ChatAccessError, chat_service

    email = await _authenticate_ws(token)
    if not email:
        await ws.close(code=4001, reason="Unauthorized")
        return

    async with AsyncSessionLocal() as db:
        try:
            user, role = await get_user_and_role(db, email)
            identity = await get_identity_for_email(db, email)
            await chat_service.get_conversation(
                db,
                conversation_id,
                identity=identity,
                user_id=user.id,
                system_role=role,
            )
        except ChatAccessError:
            await ws.close(code=4003, reason="Forbidden")
            return
        except LookupError:
            await ws.close(code=4004, reason="Not found")
            return

    channel = f"chat:{conversation_id}"
    await manager.connect(ws, channel)
    await manager.send(ws, {"type": "subscribed", "conversation_id": conversation_id})

    heartbeat_task = asyncio.create_task(_heartbeat(ws, interval=30))
    try:
        while True:
            try:
                raw = await asyncio.wait_for(ws.receive_text(), timeout=120.0)
                msg = json.loads(raw)
                if msg.get("action") == "ping":
                    await manager.send(ws, {"type": "pong", "ts": datetime.now(timezone.utc).isoformat()})
            except asyncio.TimeoutError:
                pass
    except WebSocketDisconnect:
        pass
    finally:
        heartbeat_task.cancel()
        manager.disconnect(ws, channel)
