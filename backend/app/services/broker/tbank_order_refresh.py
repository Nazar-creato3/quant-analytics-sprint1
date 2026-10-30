"""Settle broker orders (T-Bank, Finam) that were still resting when submitted."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.services.broker.finam_api import FinamApiError
from app.services.broker.tbank_api import TBankApiError, TBankClient, money

logger = get_logger(__name__)

OPEN_STATUSES = ("submitted", "partially_filled")
# A day order that has not settled after this long is checked but no longer retried forever.
_MAX_AGE = timedelta(days=3)


def apply_state(order: Any, state: dict[str, Any]) -> str:
    """Copy a GetOrderState answer onto an ExecutionOrder. Returns the new status."""
    lot = int((order.raw_response or {}).get("lot") or 1)
    status_raw = str(state.get("executionReportStatus") or "")
    lots_done = int(state.get("lotsExecuted") or 0)
    avg = money(state.get("executedOrderPrice")) or money(state.get("averagePositionPrice"))
    if lots_done:
        order.fill_quantity = float(lots_done * lot)
    if avg is not None and avg > 0:
        order.fill_price = float(avg)
    if status_raw == "EXECUTION_REPORT_STATUS_FILL":
        order.status = "filled"
        order.filled_at = datetime.now(timezone.utc)
    elif status_raw in {"EXECUTION_REPORT_STATUS_REJECTED", "EXECUTION_REPORT_STATUS_CANCELLED"}:
        # A partial fill that was then cancelled still bought something.
        order.status = "filled" if lots_done else "rejected"
        if lots_done:
            order.filled_at = datetime.now(timezone.utc)
        else:
            order.error_message = str(state.get("message") or status_raw)
    elif status_raw == "EXECUTION_REPORT_STATUS_PARTIALLYFILL":
        order.status = "partially_filled"
    raw = dict(order.raw_response or {})
    raw.update({"status": status_raw, "lots_executed": lots_done})
    order.raw_response = raw
    return order.status


def apply_finam_state(order: Any, state: dict[str, Any]) -> str:
    from app.services.broker.finam_api import dec

    status_raw = str(state.get("status") or "")
    executed = dec(state.get("executed_quantity")) or Decimal("0")
    if executed > 0:
        order.fill_quantity = float(executed)
    if status_raw == "ORDER_STATUS_FILLED":
        order.status = "filled"
        order.filled_at = datetime.now(timezone.utc)
    elif status_raw in {"ORDER_STATUS_CANCELED", "ORDER_STATUS_REJECTED", "ORDER_STATUS_EXPIRED", "ORDER_STATUS_FAILED"}:
        order.status = "filled" if executed > 0 else "rejected"
        if executed > 0:
            order.filled_at = datetime.now(timezone.utc)
        else:
            desc = state.get("status_description")
            order.error_message = str((desc or {}).get("value") if isinstance(desc, dict) else desc or status_raw)
    elif status_raw == "ORDER_STATUS_PARTIALLY_FILLED":
        order.status = "partially_filled"
    raw = dict(order.raw_response or {})
    raw.update({"status": status_raw, "executed_quantity": str(executed)})
    order.raw_response = raw
    return order.status


async def refresh_open_tbank_orders(session: AsyncSession) -> dict[str, int]:
    from app.db.models import ExecutionOrder, Maneuver, ManeuverStatus
    from app.services.trading_keys.resolver import UserTradingKeyNotFound, get_active_user_credentials

    rows = (
        await session.execute(select(ExecutionOrder).where(ExecutionOrder.status.in_(OPEN_STATUSES)))
    ).scalars().all()
    rows = [r for r in rows if (r.raw_response or {}).get("source") in {"tinkoff", "finam"} and r.broker_order_id]
    done = {"checked": 0, "filled": 0, "rejected": 0, "errors": 0}
    clients: dict[tuple[str, str, str], Any] = {}
    settled: list[str] = []
    for order in rows:
        maneuver = await session.get(Maneuver, order.maneuver_id)
        user_id = getattr(maneuver, "approved_by", None)
        raw = order.raw_response or {}
        account_id = str(raw.get("account_id") or "")
        if not user_id or not account_id:
            continue
        source = str(raw.get("source"))
        mode = "paper" if raw.get("sandbox") else str(getattr(order.trading_mode, "value", order.trading_mode) or "live")
        key = (user_id, mode, source)
        try:
            if key not in clients:
                venue = "finam" if source == "finam" else "tinkoff"
                creds = await get_active_user_credentials(
                    session, user_id=user_id, venue=venue, account_mode=mode, action="order_refresh"
                )
                token = str(creds.credentials.get("token") or creds.credentials.get("api_key") or "")
                if source == "finam":
                    from app.services.broker.finam_api import FinamClient

                    clients[key] = FinamClient(token)
                else:
                    clients[key] = TBankClient(token, sandbox=mode == "paper")
            if source == "finam":
                state = await clients[key].get_order(account_id, str(order.broker_order_id))
            else:
                state = await clients[key].get_order_state(account_id, str(order.broker_order_id))
        except (UserTradingKeyNotFound, TBankApiError, FinamApiError) as exc:
            done["errors"] += 1
            logger.warning("tbank_order_refresh_failed", order_id=order.id, error=str(exc)[:200])
            if order.submitted_at and datetime.now(timezone.utc) - order.submitted_at > _MAX_AGE:
                order.status = "error"
                order.error_message = "Статус заявки у брокера не получен"
                if maneuver is not None and maneuver.status == ManeuverStatus.EXECUTING:
                    maneuver.status = ManeuverStatus.APPROVED
            continue
        done["checked"] += 1
        status = apply_finam_state(order, state) if source == "finam" else apply_state(order, state)
        if status == "filled":
            done["filled"] += 1
            settled.append(order.maneuver_id)
        elif status == "rejected":
            done["rejected"] += 1
            if maneuver is not None and maneuver.status == ManeuverStatus.EXECUTING:
                maneuver.status = ManeuverStatus.APPROVED
    await session.commit()
    # A filled order makes the regular execution path mark the maneuver FILLED
    # (entry snapshot, lot ledger, robot plan) exactly as for an instant fill.
    from app.services.execution.adapter import execute_maneuver

    for maneuver_id in settled:
        try:
            await execute_maneuver(maneuver_id)
        except Exception as exc:  # noqa: BLE001
            logger.error("tbank_fill_settle_failed", maneuver_id=maneuver_id, error=str(exc)[:200])
    return done
