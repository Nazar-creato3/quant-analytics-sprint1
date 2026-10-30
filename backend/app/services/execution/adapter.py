"""
Execution adapter.
Paper trading by default; live requires explicit unlock.
Supports: market, limit, stop-limit orders + bracket orders with SL/TP.
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional, Protocol

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.services.execution.guard import (
    DealIntentExecutionContext,
    DirectOrderBypassError,
    ExecutionGate,
    ManualOrderExecutionContext,
    ManeuverExecutionContext,
)

logger = get_logger(__name__)

TIMEOUT = httpx.Timeout(15.0, connect=5.0)


@dataclass
class OrderRequest:
    ticker: str
    side: str           # "buy" | "sell"
    qty: float
    order_type: str     # "market" | "limit" | "stop" | "stop_limit"
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    take_profit: Optional[float] = None
    stop_loss: Optional[float] = None
    time_in_force: str = "day"
    client_order_id: Optional[str] = None
    execution_context: Optional[DealIntentExecutionContext] = None
    maneuver_context: Optional[ManeuverExecutionContext] = None
    manual_order_context: Optional[ManualOrderExecutionContext] = None


@dataclass
class OrderResult:
    broker_order_id: Optional[str]
    status: str         # "submitted" | "filled" | "rejected" | "error"
    filled_price: Optional[float]
    filled_qty: Optional[float]
    submitted_at: datetime
    filled_at: Optional[datetime] = None
    error: Optional[str] = None
    raw: dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.raw is None:
            self.raw = {}


class ExecutorProtocol(Protocol):
    async def submit_order(self, req: OrderRequest) -> OrderResult: ...


def _guard_broker_submission(req: OrderRequest) -> None:
    """Enforce DealIntent → Approval → Execution before any broker call."""
    ExecutionGate.require_executing_intent(
        req.execution_context,
        maneuver_context=req.maneuver_context,
        manual_order_context=req.manual_order_context,
    )
    try:
        from app.services.ops_desk.live_hooks import reject_new_order

        px_raw = req.limit_price if req.limit_price is not None else req.stop_price
        if px_raw is None:
            raise ValueError("нет данных")
        px = float(px_raw)
        msg = reject_new_order(ticker=req.ticker, side=req.side, qty=float(req.qty), price=px)
        if msg:
            raise ValueError(msg)
    except ValueError:
        raise
    except Exception as exc:
        raise RuntimeError("live order guard failed") from exc


def _paper_pretrade(req: OrderRequest, price: float) -> str | None:
    from app.services.pretrade.policy import evaluate

    actor: str = "human" if req.manual_order_context is not None else "auto"
    kind = "manual_order" if req.manual_order_context is not None else "strategy"
    user_id = "paper"
    if req.manual_order_context is not None:
        user_id = req.manual_order_context.manual_order_id
    try:
        decision = evaluate(
            kind=kind,  # type: ignore[arg-type]
            actor=actor,  # type: ignore[arg-type]
            user_id=user_id,
            ticker=req.ticker,
            qty=float(req.qty),
            price=float(price),
            mode="paper",
            confirmed=True,
        )
    except Exception as exc:
        return f"pretrade_unavailable:{exc}"
    if decision.verdict == "block":
        detail = decision.reasons[0].detail if decision.reasons else "risk_gate_block"
        return f"pretrade:{detail}"
    return None


class PaperExecutor:
    """
    Local paper trading simulator.
    Instantly fills market orders at the reference price — no external broker required.
    """

    async def submit_order(self, req: OrderRequest) -> OrderResult:
        _guard_broker_submission(req)
        from app.services.execution.runtime import prepare_request, record_result

        req, meta = prepare_request(req)
        if meta.get("reject"):
            now = datetime.now(timezone.utc)
            return OrderResult(
                broker_order_id=None,
                status="rejected",
                filled_price=None,
                filled_qty=None,
                submitted_at=now,
                error=str(meta["reject"]),
                raw={"simulated": True, "mode": "paper", **meta},
            )
        now = datetime.now(timezone.utc)
        fill_price = req.limit_price
        quote_bid = quote_ask = None

        if not fill_price or fill_price <= 0:
            try:
                from app.services.market_data.client import get_latest_quote_resolved

                quote = await get_latest_quote_resolved(req.ticker)
                raw_px = quote.get("price")
                if raw_px is None:
                    raw_px = quote.get("ask")
                if raw_px is None:
                    raw_px = quote.get("bid")
                if raw_px is None:
                    fill_price = None
                else:
                    fill_price = float(raw_px)
                try:
                    quote_bid = float(quote["bid"]) if quote.get("bid") is not None else None
                    quote_ask = float(quote["ask"]) if quote.get("ask") is not None else None
                except (TypeError, ValueError, KeyError):
                    quote_bid = quote_ask = None
            except Exception as exc:
                logger.warning("Paper fill price lookup failed", ticker=req.ticker, error=str(exc))
                fill_price = None

        if fill_price is None or fill_price <= 0:
            return OrderResult(
                broker_order_id=None,
                status="rejected",
                filled_price=None,
                filled_qty=None,
                submitted_at=now,
                error="нет данных",
                raw={"simulated": True, "mode": "paper"},
            )

        from app.services.execution.tca import apply_quote_or_spread

        fill_price, tca = apply_quote_or_spread(
            fill_price,
            req.side,
            symbol=req.ticker,
            bid=quote_bid,
            ask=quote_ask,
        )
        gate_err = _paper_pretrade(req, fill_price)
        if gate_err:
            return OrderResult(
                broker_order_id=None,
                status="rejected",
                filled_price=None,
                filled_qty=None,
                submitted_at=now,
                error=gate_err,
                raw={"simulated": True, "mode": "paper", "pretrade": True},
            )
        broker_id = f"paper-{uuid.uuid4().hex[:12]}"
        logger.info(
            "Paper order filled",
            ticker=req.ticker,
            side=req.side,
            qty=req.qty,
            fill_price=fill_price,
            order_id=broker_id,
        )
        result = OrderResult(
            broker_order_id=broker_id,
            status="filled",
            filled_price=round(fill_price, 4),
            filled_qty=req.qty,
            submitted_at=now,
            filled_at=now,
            error=None,
            raw={"simulated": True, "mode": "paper", "order_type": req.order_type, "tca": tca, **meta},
        )
        arrival = None
        if isinstance(tca, dict):
            arrival = tca.get("decision_mid")
        record_result(req, result, venue="paper", arrival=arrival)
        return result


def requires_broker_paper_simulation(account_mode: str | None = None) -> bool:
    """True when orders must not reach a real broker API (global lock or paper slot)."""
    if account_mode and account_mode.lower() == "paper":
        return True
    return use_local_paper_simulation()


def use_local_paper_simulation() -> bool:
    """Use internal paper fills when live trading is locked or Alpaca keys are absent."""
    if settings.live_trading_unlocked:
        return False
    if not settings.PAPER_TRADING_ENABLED:
        return False
    if not settings.ALPACA_API_KEY or not settings.ALPACA_SECRET_KEY:
        return True
    # Default: prefer local instant paper fills for approval-only workflow
    return True


def get_executor() -> ExecutorProtocol:
    """Route orders: MOEX/T-Bank → TinkoffExecutor, else paper/Alpaca."""
    from app.services.broker.tinkoff_orders import TinkoffExecutor
    from app.services.integration.historical_data import _tinkoff_token

    # Caller may pass ticker via thread-local in future; default executor is venue-agnostic.
    # submit_manual_order always uses paper for non-MOEX; MOEX routing happens in submit path.
    if _tinkoff_token():
        return _RoutingExecutor(
            tinkoff=TinkoffExecutor(),
            paper=PaperExecutor(),
            alpaca=AlpacaExecutor(),
        )
    if use_local_paper_simulation():
        return PaperExecutor()
    return AlpacaExecutor()


class _RoutingExecutor:
    """Pick T-Bank for MOEX tickers (equities + currency), otherwise paper/Alpaca."""

    def __init__(
        self,
        *,
        tinkoff: ExecutorProtocol,
        paper: ExecutorProtocol,
        alpaca: ExecutorProtocol,
    ) -> None:
        self._tinkoff = tinkoff
        self._paper = paper
        self._alpaca = alpaca

    async def submit_order(self, req: OrderRequest) -> OrderResult:
        from app.services.broker.tinkoff_orders import is_tinkoff_routable_ticker
        from app.services.execution.runtime import choose_venue, record_result

        if requires_broker_paper_simulation():
            result = await self._paper.submit_order(req)
            return result
        if is_tinkoff_routable_ticker(req.ticker):
            result = await self._tinkoff.submit_order(req)
            record_result(req, result, venue="tinkoff")
            return result
        if use_local_paper_simulation():
            return await self._paper.submit_order(req)
        venue = choose_venue(req.ticker, keyed=["alpaca"], paper_ok=False)
        result = await self._alpaca.submit_order(req)
        record_result(req, result, venue=venue if venue == "alpaca" else "alpaca")
        if result.raw is not None:
            result.raw["sor_venue"] = venue
        return result


class AlpacaExecutor:
    """
    Alpaca broker execution adapter.
    Automatically uses paper vs live endpoint based on settings.
    """

    PAPER_URL = "https://paper-api.alpaca.markets/v2"
    LIVE_URL = "https://api.alpaca.markets/v2"

    def __init__(self) -> None:
        self._is_live = settings.live_trading_unlocked
        self._base_url = self.LIVE_URL if self._is_live else self.PAPER_URL
        self._headers = {
            "APCA-API-KEY-ID": settings.ALPACA_API_KEY,
            "APCA-API-SECRET-KEY": settings.ALPACA_SECRET_KEY,
            "Content-Type": "application/json",
        }
        mode = "LIVE" if self._is_live else "PAPER"
        logger.info("Executor initialized", mode=mode, base_url=self._base_url)

    async def _post(self, path: str, body: dict) -> dict:
        url = f"{self._base_url}{path}"
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                    resp = await client.post(url, json=body, headers=self._headers)
                    resp.raise_for_status()
                    return resp.json()
            except httpx.HTTPStatusError as exc:
                body_text = exc.response.text
                logger.warning("Alpaca order error", status=exc.response.status_code, body=body_text)
                if exc.response.status_code in (400, 403, 422):
                    raise  # Don't retry client errors
                await asyncio.sleep(2 ** attempt)
            except httpx.RequestError as exc:
                if attempt == 2:
                    raise
                await asyncio.sleep(2 ** attempt)
        raise RuntimeError("Max retries exceeded on order submission")

    async def _get(self, path: str, params: dict | None = None) -> dict:
        url = f"{self._base_url}{path}"
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(url, headers=self._headers, params=params)
            resp.raise_for_status()
            return resp.json()

    async def submit_order(self, req: OrderRequest) -> OrderResult:
        """Submit an order to Alpaca (paper or live)."""
        _guard_broker_submission(req)
        if self._is_live and not settings.live_trading_unlocked:
            return OrderResult(
                broker_order_id=None, status="rejected",
                filled_price=None, filled_qty=None,
                submitted_at=datetime.now(timezone.utc),
                error="Live trading not unlocked",
                raw={},
            )

        body: dict[str, Any] = {
            "symbol": req.ticker,
            "side": req.side,
            "type": req.order_type,
            "time_in_force": req.time_in_force,
        }

        try:
            from app.services.execution.alpaca_qty import alpaca_order_qty_fields

            body.update(alpaca_order_qty_fields(req.qty, req.limit_price))
        except ValueError as exc:
            return OrderResult(
                broker_order_id=None,
                status="rejected",
                filled_price=None,
                filled_qty=None,
                submitted_at=datetime.now(timezone.utc),
                error=str(exc),
                raw={},
            )

        if req.limit_price:
            body["limit_price"] = str(round(req.limit_price, 2))
        if req.stop_price:
            body["stop_price"] = str(round(req.stop_price, 2))
        if req.client_order_id:
            body["client_order_id"] = req.client_order_id

        # Bracket order (SL + TP simultaneously)
        if req.take_profit or req.stop_loss:
            body["order_class"] = "bracket"
            if req.take_profit:
                body["take_profit"] = {"limit_price": str(round(req.take_profit, 2))}
            if req.stop_loss:
                body["stop_loss"] = {"stop_price": str(round(req.stop_loss, 2))}

        try:
            raw = await self._post("/orders", body)
            status = raw.get("status", "submitted")
            logger.info(
                "Order submitted",
                ticker=req.ticker, side=req.side, qty=req.qty,
                order_id=raw.get("id"), status=status,
                mode="live" if self._is_live else "paper",
            )
            return OrderResult(
                broker_order_id=raw.get("id"),
                status=status,
                filled_price=float(raw["filled_avg_price"]) if raw.get("filled_avg_price") else None,
                filled_qty=float(raw["filled_qty"]) if raw.get("filled_qty") else None,
                submitted_at=datetime.now(timezone.utc),
                error=None,
                raw=raw,
            )
        except httpx.HTTPStatusError as exc:
            error_msg = exc.response.text[:500]
            logger.error("Order rejected", ticker=req.ticker, error=error_msg)
            return OrderResult(
                broker_order_id=None, status="rejected",
                filled_price=None, filled_qty=None,
                submitted_at=datetime.now(timezone.utc),
                error=error_msg, raw={},
            )
        except Exception as exc:
            logger.error("Order submission failed", ticker=req.ticker, error=str(exc))
            return OrderResult(
                broker_order_id=None, status="error",
                filled_price=None, filled_qty=None,
                submitted_at=datetime.now(timezone.utc),
                error=str(exc), raw={},
            )

    async def get_order_status(self, broker_order_id: str) -> dict:
        """Poll order status from Alpaca."""
        return await self._get(f"/orders/{broker_order_id}")

    async def cancel_order(self, broker_order_id: str) -> bool:
        """Cancel an open order."""
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                resp = await client.delete(
                    f"{self._base_url}/orders/{broker_order_id}",
                    headers=self._headers,
                )
                return resp.status_code == 204
        except Exception as exc:
            logger.error("Cancel order failed", order_id=broker_order_id, error=str(exc))
            return False

    async def get_account(self) -> dict:
        """Get account info including buying power and equity."""
        return await self._get("/account")

    async def get_positions(self) -> list[dict]:
        """Get all open positions."""
        return await self._get("/positions")


# ── Execution task ────────────────────────────────────────────────────────────

async def execute_maneuver(maneuver_id: str) -> None:
    """
    Execute a single approved maneuver.
    Fetches maneuver from DB, builds OrderRequest, submits to broker,
    updates DB with result.
    """
    from sqlalchemy import select

    from app.db.models import ExecutionOrder, Maneuver, ManeuverStatus, SignalDirection, StrategyType
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        try:
            await _execute_maneuver_in_session(session, maneuver_id)
        except Exception as exc:
            await session.rollback()
            logger.error("Maneuver execution failed", maneuver_id=maneuver_id, error=str(exc))
            try:
                result = await session.execute(
                    select(Maneuver).where(Maneuver.id == maneuver_id)
                )
                maneuver = result.scalar_one_or_none()
                if maneuver and maneuver.status == ManeuverStatus.EXECUTING:
                    maneuver.status = ManeuverStatus.APPROVED
                    await session.commit()
            except Exception as reset_exc:
                await session.rollback()
                logger.error(
                    "Failed to reset maneuver after execution error",
                    maneuver_id=maneuver_id,
                    error=str(reset_exc),
                )


async def _execute_maneuver_in_session(session, maneuver_id: str) -> None:
    from sqlalchemy import select

    from app.db.models import ExecutionOrder, Maneuver, ManeuverStatus, SignalDirection, StrategyType

    result = await session.execute(
        select(Maneuver).where(Maneuver.id == maneuver_id)
    )
    maneuver = result.scalar_one_or_none()
    if not maneuver:
        logger.error("Maneuver not found for execution", maneuver_id=maneuver_id)
        return
    # Used by the robot-plan backfill and bracket lookup below, before the executor step.
    exec_user_id = maneuver.approved_by

    if maneuver.status == ManeuverStatus.FILLED:
        logger.info("Maneuver already filled", maneuver_id=maneuver_id)
        return

    if maneuver.status not in (ManeuverStatus.APPROVED, ManeuverStatus.EXECUTING):
        logger.warning(
            "Maneuver not approved, skipping",
            maneuver_id=maneuver_id,
            status=maneuver.status,
        )
        return

    strategy = (
        maneuver.strategy_type.value
        if hasattr(maneuver.strategy_type, "value")
        else str(maneuver.strategy_type)
    )
    if strategy == StrategyType.NO_TRADE.value:
        logger.info("NO_TRADE maneuver, skipping execution", maneuver_id=maneuver_id)
        return

    existing_order = await session.execute(
        select(ExecutionOrder)
        .where(ExecutionOrder.maneuver_id == maneuver_id)
        .order_by(ExecutionOrder.submitted_at.desc())
        .limit(1)
    )
    existing = existing_order.scalar_one_or_none()
    if existing is not None:
        if existing.status == "filled":
            if maneuver.status != ManeuverStatus.FILLED:
                maneuver.status = ManeuverStatus.FILLED
                maneuver.fill_price = existing.fill_price
                maneuver.filled_at = existing.filled_at
                from app.services.portfolio.entry_snapshot import capture_entry_snapshot

                await capture_entry_snapshot(
                    db=session,
                    maneuver=maneuver,
                    fill_price=existing.fill_price,
                )
                # Backfill Robot Core if fill existed before ledger
                try:
                    owner_id = None
                    if maneuver.report_id:
                        from app.db.models import ManeuverReport

                        rep = await session.get(ManeuverReport, maneuver.report_id)
                        owner_id = getattr(rep, "created_by", None) if rep else None
                    if not owner_id and exec_user_id:
                        owner_id = exec_user_id
                    if owner_id and existing.fill_price and existing.fill_quantity:
                        from app.services.portfolio.lot_ledger import record_maneuver_fill
                        from app.services.robot.plan import ensure_plan_for_maneuver

                        plan = await ensure_plan_for_maneuver(
                            session,
                            user_id=owner_id,
                            maneuver=maneuver,
                            mode=str(getattr(maneuver.trading_mode, "value", maneuver.trading_mode) or "paper"),
                        )
                        await record_maneuver_fill(
                            session,
                            user_id=owner_id,
                            maneuver_id=maneuver.id,
                            ticker=maneuver.ticker,
                            direction=str(getattr(maneuver.direction, "value", maneuver.direction)),
                            fill_price=float(existing.fill_price),
                            # Broker fills are true shares; the ledger keeps the internal unit.
                            qty=float(existing.fill_quantity)
                            * float((existing.raw_response or {}).get("qty_scale") or 1.0),
                            robot_plan_id=plan.id,
                        )
                except Exception as lot_exc:
                    logger.warning(
                        "robot_core_backfill_hook_failed",
                        maneuver_id=maneuver_id,
                        error=str(lot_exc)[:200],
                    )
                await session.commit()
            logger.info("Maneuver already has filled order", maneuver_id=maneuver_id)
            return
        if maneuver.status == ManeuverStatus.EXECUTING:
            logger.info("Maneuver execution already in progress", maneuver_id=maneuver_id)
            return

    if maneuver.status == ManeuverStatus.APPROVED:
        maneuver.status = ManeuverStatus.EXECUTING
        await session.commit()

    direction = (
        maneuver.direction.value
        if hasattr(maneuver.direction, "value")
        else str(maneuver.direction)
    )
    side = "buy" if direction == SignalDirection.LONG.value else "sell"

    from app.core.config import settings as app_settings
    from app.services.compliance.trading_placement_audit import (
        record_trading_placement_request,
        resolve_broker_mode,
    )
    from app.services.execution.adapter import use_local_paper_simulation
    from app.utils.json_safe import coerce_finite_float, finite_float

    position_usd = coerce_finite_float(maneuver.position_size_usd, 0.0)
    if position_usd <= 0:
        logger.error(
            "Refuse paper fill with zero size",
            maneuver_id=maneuver_id,
            ticker=maneuver.ticker,
        )
        maneuver.status = ManeuverStatus.APPROVED
        await session.commit()
        return

    reference_price = finite_float(maneuver.entry_zone_low) or finite_float(maneuver.entry_zone_high)
    if reference_price is None or reference_price <= 0:
        try:
            from app.services.market_data.client import get_latest_quote_resolved

            quote = await get_latest_quote_resolved(maneuver.ticker)
            raw_px = quote.get("price")
            if raw_px is None:
                raw_px = quote.get("ask")
            if raw_px is None:
                raw_px = quote.get("bid")
            reference_price = finite_float(raw_px)
        except Exception as exc:
            logger.warning("Reference price lookup failed", ticker=maneuver.ticker, error=str(exc))
            reference_price = None

    if reference_price is None or reference_price <= 0:
        logger.error(
            "Refuse paper fill without reference price",
            maneuver_id=maneuver_id,
            ticker=maneuver.ticker,
        )
        maneuver.status = ManeuverStatus.APPROVED
        await session.commit()
        return

    qty = position_usd / reference_price
    if qty <= 0 or not (qty == qty):  # NaN guard
        logger.error(
            "Refuse paper fill with invalid qty",
            maneuver_id=maneuver_id,
            ticker=maneuver.ticker,
        )
        maneuver.status = ManeuverStatus.APPROVED
        await session.commit()
        return

    # Internal quantity is USD notional / native price (P&L and risk stay
    # correct as ratios). A real order needs true shares in the instrument's
    # currency; internal records keep the internal unit via qty_scale.
    trading_mode_now = str(getattr(maneuver.trading_mode, "value", maneuver.trading_mode) or "paper")
    broker_qty = qty
    qty_scale = 1.0
    if trading_mode_now == "live":
        from app.services.market_data.fx_rates import native_qty

        converted = await native_qty(maneuver.ticker, position_usd, reference_price)
        if converted is None:
            maneuver.status = ManeuverStatus.APPROVED
            session.add(
                ExecutionOrder(
                    maneuver_id=maneuver_id,
                    ticker=maneuver.ticker,
                    side=side,
                    quantity=qty,
                    order_type="market",
                    limit_price=reference_price,
                    status="rejected",
                    trading_mode=maneuver.trading_mode,
                    error_message="Нет курса валюты для пересчёта размера заявки",
                    raw_response={},
                )
            )
            await session.commit()
            logger.error("Live order without FX rate refused", maneuver_id=maneuver_id, ticker=maneuver.ticker)
            return
        broker_qty, qty_scale = converted

    stop_loss = maneuver.stop_loss
    take_profit = maneuver.take_profit
    try:
        from app.db.robot_models import RobotPlan
        from app.services.robot.live_sync import brackets_from_levels
        from sqlalchemy import select

        if exec_user_id:
            prow = await session.execute(
                select(RobotPlan)
                .where(
                    RobotPlan.maneuver_id == maneuver_id,
                    RobotPlan.user_id == exec_user_id,
                    RobotPlan.status == "active",
                )
                .limit(1)
            )
            rplan = prow.scalar_one_or_none()
            if rplan is not None:
                br = brackets_from_levels(rplan.levels)
                if br.get("stop_loss") is not None:
                    stop_loss = br["stop_loss"]
                if br.get("take_profit") is not None:
                    take_profit = br["take_profit"]
    except Exception as exc:
        logger.warning(
            "robot plan brackets lookup failed",
            maneuver_id=maneuver_id,
            error=str(exc)[:200],
        )

    req = OrderRequest(
        ticker=maneuver.ticker,
        side=side,
        qty=broker_qty,
        order_type="market",
        limit_price=reference_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        client_order_id=f"maneuver-{maneuver_id}",
        maneuver_context=ManeuverExecutionContext(
            maneuver_id=maneuver_id,
            status=(
                maneuver.status.value
                if hasattr(maneuver.status, "value")
                else str(maneuver.status)
            ),
        ),
    )

    trading_mode_val = (
        maneuver.trading_mode.value
        if hasattr(maneuver.trading_mode, "value")
        else str(maneuver.trading_mode or "paper")
    )
    await record_trading_placement_request(
        session,
        user_id=maneuver.approved_by,
        actor_email=None,
        resource_type="maneuver",
        resource_id=maneuver_id,
        symbol=maneuver.ticker,
        side=side,
        broker_mode=resolve_broker_mode(
            live_unlocked=app_settings.live_trading_unlocked,
            paper_sim=use_local_paper_simulation(),
        ),
        trading_mode=trading_mode_val,
        details={
            "qty": req.qty,
            "order_type": req.order_type,
            "client_order_id": req.client_order_id,
        },
        commit=False,
    )

    exec_user_id = maneuver.approved_by
    if not exec_user_id:
        maneuver.status = ManeuverStatus.APPROVED
        await session.commit()
        logger.error("Maneuver missing approved_by — cannot resolve user key", maneuver_id=maneuver_id)
        return
    from app.services.trading_keys.user_executor import (
        TradingKeyRequiredError,
        get_user_executor,
    )

    try:
        executor = await get_user_executor(
            session,
            user_id=exec_user_id,
            ticker=maneuver.ticker,
            account_mode=trading_mode_val,
        )
    except TradingKeyRequiredError as exc:
        maneuver.status = ManeuverStatus.APPROVED
        await session.commit()
        logger.error("Maneuver execution blocked — no user key", maneuver_id=maneuver_id, error=str(exc))
        return
    order_result = await executor.submit_order(req)

    if order_result.status == "filled" and order_result.filled_price:
        fill_price = float(order_result.filled_price)
        fill_qty = float(order_result.filled_qty * qty_scale) if order_result.filled_qty else qty
        session.add(
            ExecutionOrder(
                maneuver_id=maneuver_id,
                broker_order_id=order_result.broker_order_id,
                ticker=maneuver.ticker,
                side=side,
                quantity=fill_qty,
                order_type="market",
                limit_price=reference_price,
                stop_price=maneuver.stop_loss,
                status="filled",
                trading_mode=maneuver.trading_mode,
                submitted_at=order_result.submitted_at,
                filled_at=order_result.filled_at or datetime.now(timezone.utc),
                fill_price=fill_price,
                fill_quantity=fill_qty,
                raw_response=order_result.raw or {},
            )
        )
        maneuver.status = ManeuverStatus.FILLED
        maneuver.fill_price = fill_price
        maneuver.filled_at = order_result.filled_at or datetime.now(timezone.utc)
        from app.services.portfolio.entry_snapshot import capture_entry_snapshot

        await capture_entry_snapshot(db=session, maneuver=maneuver, fill_price=fill_price)
        # Robot Core: lot ledger + plan
        try:
            owner_id = None
            if maneuver.report_id:
                from app.db.models import ManeuverReport

                rep = await session.get(ManeuverReport, maneuver.report_id)
                owner_id = getattr(rep, "created_by", None) if rep else None
            if not owner_id and exec_user_id:
                owner_id = exec_user_id
            if owner_id:
                from app.services.portfolio.lot_ledger import record_maneuver_fill
                from app.services.robot.plan import ensure_plan_for_maneuver

                plan = await ensure_plan_for_maneuver(
                    session,
                    user_id=owner_id,
                    maneuver=maneuver,
                    mode=str(getattr(maneuver.trading_mode, "value", maneuver.trading_mode) or "paper"),
                )
                await record_maneuver_fill(
                    session,
                    user_id=owner_id,
                    maneuver_id=maneuver.id,
                    ticker=maneuver.ticker,
                    direction=str(getattr(maneuver.direction, "value", maneuver.direction)),
                    fill_price=fill_price,
                    qty=fill_qty,
                    robot_plan_id=plan.id,
                )
        except Exception as lot_exc:
            logger.warning(
                "robot_core_fill_hook_failed",
                maneuver_id=maneuver_id,
                error=str(lot_exc)[:200],
            )
        await session.commit()
        logger.info(
            "Maneuver filled",
            maneuver_id=maneuver_id,
            ticker=maneuver.ticker,
            fill_price=fill_price,
            qty=fill_qty,
        )
        return

    if order_result.status in ("submitted", "partially_filled"):
        # Resting at the broker (limit, partial, or a market order still in
        # flight). Keep the maneuver EXECUTING and let the order refresher
        # settle it; recording the order also stops a second submission.
        session.add(
            ExecutionOrder(
                maneuver_id=maneuver_id,
                broker_order_id=order_result.broker_order_id,
                ticker=maneuver.ticker,
                side=side,
                quantity=qty,
                order_type=req.order_type,
                limit_price=reference_price,
                stop_price=maneuver.stop_loss,
                status=order_result.status,
                trading_mode=maneuver.trading_mode,
                submitted_at=order_result.submitted_at,
                fill_quantity=order_result.filled_qty,
                fill_price=order_result.filled_price,
                raw_response={**(order_result.raw or {}), "qty_scale": qty_scale},
            )
        )
        await session.commit()
        logger.info(
            "Maneuver order resting at broker",
            maneuver_id=maneuver_id,
            broker_order_id=order_result.broker_order_id,
            status=order_result.status,
        )
        return

    if order_result.status in ("rejected", "error"):
        maneuver.status = ManeuverStatus.APPROVED
        session.add(
            ExecutionOrder(
                maneuver_id=maneuver_id,
                broker_order_id=order_result.broker_order_id,
                ticker=maneuver.ticker,
                side=side,
                quantity=qty,
                order_type="market",
                limit_price=reference_price,
                stop_price=maneuver.stop_loss,
                status=order_result.status,
                trading_mode=maneuver.trading_mode,
                submitted_at=order_result.submitted_at,
                error_message=order_result.error,
                raw_response=order_result.raw or {},
            )
        )
        await session.commit()
        logger.error(
            "Maneuver execution failed",
            maneuver_id=maneuver_id,
            error=order_result.error,
            status=order_result.status,
        )


_executor: AlpacaExecutor | None = None


def get_alpaca_executor() -> AlpacaExecutor:
    global _executor
    if _executor is None:
        _executor = AlpacaExecutor()
    return _executor
