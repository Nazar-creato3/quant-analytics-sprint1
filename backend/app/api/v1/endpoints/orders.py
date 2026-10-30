"""Manual order ticket API (spec B.1–B.4)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user_email, get_user_db
from app.core.logging import get_logger
from app.db.models import ManualOrder, User
from app.schemas.orders import (
    ManualOrderCreate,
    ManualOrderModify,
    ManualOrderOut,
    OrderBookSnapshot,
    OrderPrefillFromManeuver,
    OrderTicketPrefill,
    RecentTrade,
    SlippageEstimate,
    SymbolTradingRulesOut,
)
from app.services.orders.service import (
    _to_out,
    build_prefill_from_maneuver,
    cancel_manual_order,
    get_order_book,
    get_recent_trades,
    modify_manual_order,
    submit_manual_order,
)
from app.services.orders.slippage import estimate_slippage
from app.services.orders.conditional_manager import poll_conditional_orders
from app.services.orders.symbol_rules import get_symbol_trading_rules
from app.services.portfolio.metrics import _user_effective_deploy_cap

router = APIRouter(prefix="/orders", tags=["orders"])
logger = get_logger(__name__)


@router.post("/machine")
def post_order_machine(
    body: dict,
    email: str = Depends(get_current_user_email),
) -> dict:
    """Paper order machine. Live is refused inside submit_order."""
    from app.services.order_machine.service import submit_order

    return submit_order(
        user_id=email,
        client_order_id=str(body.get("client_order_id") or ""),
        ticker=str(body.get("ticker") or ""),
        side=str(body.get("side") or ""),
        qty=str(body.get("qty") or "0"),
        ccy=str(body.get("ccy") or ""),
        price=body.get("price"),
        order_type=str(body.get("order_type") or "limit"),
        mode=str(body.get("mode") or "paper"),
        actor="human",
        confirmed=bool(body.get("confirmed")),
        instrument_kind=str(body.get("instrument_kind") or "equity"),
        maneuver_key=body.get("maneuver_key"),
        venue=str(body.get("venue") or "paper"),
    )


@router.get("/machine/{client_order_id}")
def get_order_machine(
    client_order_id: str,
    email: str = Depends(get_current_user_email),
) -> dict:
    from app.services.order_machine.service import get_order

    row = get_order(client_order_id)
    if row is None or row.get("user_id") != email:
        raise HTTPException(status_code=404, detail="нет данных")
    return row


@router.post("", response_model=ManualOrderOut, status_code=status.HTTP_201_CREATED)
async def create_manual_order(
    body: ManualOrderCreate,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> ManualOrderOut:
    """Submit a manual order from the order ticket — never auto-executes from maneuvers."""
    from app.services.execution.guard import DirectOrderBypassError
    from app.services.instrument.data_only import DataOnlyInstrumentError

    user_result = await db.execute(select(User).where(User.email == email))
    user = user_result.scalar_one_or_none()
    try:
        return await submit_manual_order(
            db,
            body,
            user_id=user.id if user else None,
            user_email=email,
        )
    except DataOnlyInstrumentError as exc:
        logger.warning(
            "manual_order_data_only_rejected",
            email=email,
            ticker=body.ticker,
            error=str(exc),
        )
        # GA16-330: client sees generic text; details stay in logs.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="По этой бумаге заявку разместить нельзя.",
        )
    except ValueError as exc:
        logger.warning(
            "manual_order_validation_failed",
            email=email,
            ticker=body.ticker,
            order_type=body.order_type,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Проверьте параметры заявки и попробуйте снова.",
        )
    except DirectOrderBypassError as exc:
        logger.warning(
            "manual_order_execution_blocked",
            email=email,
            ticker=body.ticker,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Заявку сейчас отправить нельзя.",
        )
    except Exception:
        logger.exception(
            "manual_order_submit_failed",
            email=email,
            ticker=body.ticker,
            order_type=body.order_type,
            side=body.side,
            quantity=body.quantity,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Не удалось разместить заявку. Попробуйте позже.",
        )


@router.get("", response_model=list[ManualOrderOut])
async def list_manual_orders(
    ticker: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> list[ManualOrderOut]:
    user_result = await db.execute(select(User).where(User.email == email))
    user = user_result.scalar_one_or_none()
    if not user:
        return []
    query = select(ManualOrder).where(ManualOrder.user_id == user.id).order_by(desc(ManualOrder.created_at))
    if ticker:
        query = query.where(ManualOrder.ticker == ticker.upper())
    if status_filter:
        query = query.where(ManualOrder.status == status_filter)
    result = await db.execute(query.limit(limit))
    return [_to_out(row) for row in result.scalars().all()]


@router.post("/prefill/maneuver", response_model=OrderTicketPrefill)
async def prefill_from_maneuver(
    body: OrderPrefillFromManeuver,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> OrderTicketPrefill:
    """Build order ticket prefill from a maneuver — user still submits manually."""
    user_result = await db.execute(select(User).where(User.email == email))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    portfolio_size = await _user_effective_deploy_cap(email, db)
    try:
        return await build_prefill_from_maneuver(
            db,
            body.maneuver_id,
            portfolio_size=portfolio_size,
            user_id=user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/book/{ticker}", response_model=OrderBookSnapshot)
async def order_book(
    ticker: str,
    email: str = Depends(get_current_user_email),
) -> OrderBookSnapshot:
    return await get_order_book(ticker.upper())


@router.get("/recent-trades/{ticker}", response_model=list[RecentTrade])
async def recent_trades(
    ticker: str,
    limit: int = Query(50, ge=1, le=200),
    email: str = Depends(get_current_user_email),
) -> list[RecentTrade]:
    return await get_recent_trades(ticker.upper(), limit=limit)


@router.get("/symbol-rules/{ticker}", response_model=SymbolTradingRulesOut)
async def symbol_trading_rules(
    ticker: str,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> SymbolTradingRulesOut:
    from app.services.execution.capability import resolve_execution_capability
    from app.services.instrument.data_only import execution_flags, is_data_only_symbol
    from app.services.portfolio.user_scope import get_user_by_email

    sym = ticker.upper()
    if is_data_only_symbol(sym):
        flags = execution_flags(sym)
        feed = flags.get("feed")
        if feed == "forex":
            venue = "forex_data"
        elif feed == "commodities":
            venue = "commodities_data"
        else:
            venue = "marketstack_eod"
        return SymbolTradingRulesOut(
            ticker=sym,
            venue=venue,
            tick_size=0.01,
            lot_size=1.0,
            min_qty=1.0,
            data_only=True,
            execution_enabled=False,
            feed_label_ru=str(flags.get("feed_label_ru") or ""),
            execution_block_type="unavailable",
            globally_tradeable=False,
        )

    user = await get_user_by_email(db, email)
    user_id = user.id if user else None

    rules = await get_symbol_trading_rules(sym)
    capability = await resolve_execution_capability(db, ticker=sym, user_id=user_id)
    flags = execution_flags(sym)
    required_providers = (
        [p.display_name_ru for p in capability.providers if p.exchange_supports and not p.user_connected]
        if capability.block_type == "connect_provider"
        else None
    )
    venue = capability.primary_venue or rules.venue
    return SymbolTradingRulesOut.model_validate(rules.model_dump()).model_copy(
        update={
            "venue": venue,
            "data_only": bool(flags.get("data_only")),
            "execution_enabled": capability.execution_enabled,
            "feed_label_ru": capability.block_reason_ru or flags.get("feed_label_ru"),
            "bybit_tokenized_listed": capability.bybit_tokenized_listed,
            "execution_block_type": capability.block_type,
            "globally_tradeable": capability.globally_tradeable,
            "required_providers_ru": required_providers,
        }
    )


@router.get("/slippage/{ticker}", response_model=SlippageEstimate)
async def slippage_estimate(
    ticker: str,
    notional_usd: float = Query(..., gt=0),
    email: str = Depends(get_current_user_email),
) -> SlippageEstimate:
    return await estimate_slippage(ticker.upper(), notional_usd)


@router.post("/conditional/poll")
async def poll_conditional(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> dict:
    """Staff-only: poll conditional OCO/trailing watchers (also run by scheduler)."""
    from app.core.rbac_deps import get_user_and_role
    from app.domain.rbac import has_permission

    _user, role = await get_user_and_role(db, email)
    if not has_permission(role, "ops.read") and not has_permission(role, "*"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="ops.read required")
    triggered = await poll_conditional_orders(db)
    return {"triggered": triggered}


@router.get("/{order_id}", response_model=ManualOrderOut)
async def get_manual_order(
    order_id: str,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> ManualOrderOut:
    user_result = await db.execute(select(User).where(User.email == email))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Order not found")
    result = await db.execute(
        select(ManualOrder).where(
            ManualOrder.id == order_id,
            ManualOrder.user_id == user.id,
        )
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return _to_out(order)


@router.patch("/{order_id}", response_model=ManualOrderOut)
async def modify_order(
    order_id: str,
    body: ManualOrderModify,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> ManualOrderOut:
    """Modify price or quantity on a working limit/stop-limit order."""
    user_result = await db.execute(select(User).where(User.email == email))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Order not found")
    try:
        return await modify_manual_order(
            db,
            order_id,
            limit_price=body.limit_price,
            quantity=body.quantity,
            user_id=user.id if user else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/{order_id}/cancel", response_model=ManualOrderOut)
async def cancel_order(
    order_id: str,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> ManualOrderOut:
    user_result = await db.execute(select(User).where(User.email == email))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Order not found")
    try:
        return await cancel_manual_order(db, order_id, user_id=user.id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
