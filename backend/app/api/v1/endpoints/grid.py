"""
Grid bot management endpoints.
Create, list, inspect, and stop grid bots.
State is persisted in Redis (ephemeral) and summarised in DB audit.
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.core.deps import get_current_user_email, get_db
from app.core.logging import get_logger
from app.core.access_deps import require_access
from app.domain.access_policy import AccessAction
from app.db.models import User
from app.utils.audit import AuditAction, audit
from app.utils.cache import cache_delete, cache_get, cache_set

logger = get_logger(__name__)
router = APIRouter(prefix="/grid", tags=["grid bots"])

_GRID_KEY = "grid:bots"          # Redis hash of bot_id -> serialised GridState
_GRID_TTL = 60 * 60 * 24 * 30   # 30 days
# In-process fallback when Redis is unavailable (dev / single-node)
_memory_bots: dict[str, dict] = {}


# ── Schemas ───────────────────────────────────────────────────────────────────

class CreateGridRequest(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=24)
    lower_price: float = Field(..., gt=0)
    upper_price: float = Field(..., gt=0)
    grid_count: int = Field(10, ge=2, le=100)
    total_capital: float = Field(..., gt=0)
    take_profit: float | None = None
    stop_loss: float | None = None
    current_price: float = Field(..., gt=0, description="Entry price to initialise levels")
    grid_type: str = Field("geometric", pattern="^(arithmetic|geometric)$")
    trailing_enabled: bool = False
    trailing_offset_pct: float = Field(0.02, ge=0.001, le=0.5)
    dca_enabled: bool = True
    level_take_profit_pct: float = Field(0.015, ge=0.0001, le=0.5)
    level_stop_loss_pct: float = Field(0.02, ge=0.0001, le=0.5)
    level_max_hold_hours: float = Field(72.0, ge=1.0, le=8760.0)
    fee_bps: float = Field(10.0, ge=0.0, le=100.0)
    slippage_bps: float = Field(5.0, ge=0.0, le=100.0)


class GridSummaryOut(BaseModel):
    bot_id: str
    ticker: str
    lower_price: float
    upper_price: float
    grid_count: int
    grid_type: str = "geometric"
    total_capital: float
    is_active: bool
    is_paused: bool = False
    total_trades: int
    realized_pnl: float
    unrealized_pnl: float
    total_pnl: float
    last_price: float | None
    pending_orders: int
    filled_orders: int
    last_activity_at: str | None = None
    session_pnl: float = 0.0
    executor_state: str = "grid_active"
    is_legacy: bool = True
    migration_hint: str = "Legacy grid bot — migrate levels to RobotPlan (plan_type=grid)"


class GridLevelOut(BaseModel):
    price: float
    side: str
    status: str
    quantity: float
    fill_price: float | None = None
    pnl: float = 0.0
    barrier_id: str | None = None
    barrier_status: str = "none"


class GridEventOut(BaseModel):
    ts: str
    type: str
    message: str
    price: float | None = None
    pnl_delta: float | None = None
    side: str | None = None


class GridPnlSnapshotOut(BaseModel):
    ts: str
    total_pnl: float


class GridActivityOut(BaseModel):
    bot_id: str
    ticker: str
    last_price: float | None
    last_activity_at: str | None
    session_pnl: float
    total_pnl: float
    realized_pnl: float
    unrealized_pnl: float
    pending_levels: list[GridLevelOut]
    recent_fills: list[GridLevelOut]
    recent_events: list[GridEventOut]
    pnl_snapshots: list[GridPnlSnapshotOut]
    paper_trades: list[dict[str, Any]] = Field(default_factory=list)
    open_positions: list[dict[str, Any]] = Field(default_factory=list)
    pending_orders: int
    filled_orders: int
    lower_price: float | None = None
    upper_price: float | None = None
    grid_count: int | None = None
    is_active: bool = True
    is_paused: bool = False
    total_trades: int = 0
    total_capital: float | None = None
    grid_levels: list[GridLevelOut] = Field(default_factory=list)
    grid_type: str = "geometric"
    executor_state: str = "grid_active"
    circuit_breaker: dict[str, Any] | None = None
    dca_state: dict[str, Any] | None = None
    barrier_positions: list[dict[str, Any]] = Field(default_factory=list)
    trailing_enabled: bool = False


class AutoCalibrateRequest(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=24)
    total_capital: float = Field(..., gt=0)
    risk_level: str = Field("medium", pattern="^(low|medium|high)$")
    grid_type: str | None = Field(None, pattern="^(arithmetic|geometric)$")


class GridBacktestRequest(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=24)
    lower_price: float = Field(..., gt=0)
    upper_price: float = Field(..., gt=0)
    grid_count: int = Field(10, ge=2, le=100)
    total_capital: float = Field(..., gt=0)
    grid_type: str = Field("geometric", pattern="^(arithmetic|geometric)$")
    fee_bps: float = Field(10.0, ge=0.0, le=100.0)
    slippage_bps: float = Field(5.0, ge=0.0, le=100.0)
    leverage: float = Field(1.0, ge=1.0, le=125.0)
    bar_limit: int = Field(90, ge=30, le=365)


class UpdateGridConfigRequest(BaseModel):
    grid_count: int | None = Field(None, ge=2, le=100)
    lower_price: float | None = Field(None, gt=0)
    upper_price: float | None = Field(None, gt=0)
    total_capital: float | None = Field(None, gt=0)


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _load_all_bots() -> dict[str, dict]:
    raw = await cache_get(_GRID_KEY)
    if raw is not None:
        _memory_bots.clear()
        _memory_bots.update(raw)
        return raw
    return dict(_memory_bots)


async def _load_user_bots(email: str) -> dict[str, dict]:
    from app.services.portfolio.user_scope import filter_grid_bots_for_user

    return filter_grid_bots_for_user(await _load_all_bots(), email)


async def _save_all_bots(bots: dict[str, dict]) -> None:
    _memory_bots.clear()
    _memory_bots.update(bots)
    ok = await cache_set(_GRID_KEY, bots, ttl=_GRID_TTL)
    if not ok:
        logger.warning(
            "Redis unavailable — grid bots persisted in memory only (lost on restart)",
            bot_count=len(bots),
        )


def _summary_out(bot_id: str, data: dict[str, Any]) -> GridSummaryOut:
    from app.services.grid.tick import recompute_summary, session_pnl

    data = recompute_summary(data)
    s = data.get("summary", {})
    cfg = data.get("config", {})
    return GridSummaryOut(
        bot_id=bot_id,
        ticker=s.get("ticker", cfg.get("ticker", "")),
        lower_price=cfg["lower_price"],
        upper_price=cfg["upper_price"],
        grid_count=cfg["grid_count"],
        grid_type=cfg.get("grid_type", "geometric"),
        total_capital=cfg["total_capital"],
        is_active=data.get("is_active", True),
        is_paused=data.get("is_paused", False),
        total_trades=data.get("total_trades", 0),
        realized_pnl=data.get("realized_pnl", 0.0),
        unrealized_pnl=s.get("unrealized_pnl", 0.0),
        total_pnl=data.get("realized_pnl", 0.0) + s.get("unrealized_pnl", 0.0),
        last_price=s.get("last_price"),
        pending_orders=s.get("pending_orders", 0),
        filled_orders=s.get("filled_orders", 0),
        last_activity_at=data.get("last_activity_at"),
        session_pnl=session_pnl(data),
        executor_state=data.get("executor_state", "grid_active"),
    )


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("", response_model=GridSummaryOut, status_code=status.HTTP_201_CREATED)
async def create_grid_bot(
    body: CreateGridRequest,
    email: str = Depends(get_current_user_email),
    db=Depends(get_db),
    _: User = Depends(require_access(AccessAction.MANAGE_GRID)),
) -> GridSummaryOut:
    """Create and initialise a new grid bot."""
    from app.services.grid.engine import GridBotEngine, GridConfig
    from app.services.grid.tick import init_activity_state
    import uuid

    if body.lower_price >= body.upper_price:
        raise HTTPException(400, "lower_price must be less than upper_price")

    from app.services.bot_risk.guard import build_snapshot_from_stores, get_bot_risk_guard

    guard = get_bot_risk_guard()
    stop_loss = body.stop_loss
    if stop_loss is None:
        stop_loss = guard.default_grid_stop_loss(body.lower_price)

    existing = await _load_all_bots()
    snapshot = build_snapshot_from_stores(grid=existing)
    corr = guard.check_correlation(
        ticker=body.ticker.upper(),
        snapshot=snapshot,
    )
    if not corr.allowed:
        raise HTTPException(400, corr.reason)

    from app.services.portfolio.capital_overlap import maneuver_occupied_tickers_for_email

    locked = await maneuver_occupied_tickers_for_email(db, email)
    if body.ticker.upper() in locked:
        raise HTTPException(
            400,
            f"Тикер {body.ticker.upper()} уже в открытом манёвре — сетку не открываем (один капитал).",
        )
    from app.services.forecast.daily_book import score_20_for_symbol

    beat_score = score_20_for_symbol(body.ticker)
    if beat_score is not None and beat_score <= 3:
        raise HTTPException(
            400,
            f"Скор {body.ticker.upper()} = {beat_score}/10 — сетку не открываем на слабом ранге.",
        )

    cfg = GridConfig(
        ticker=body.ticker.upper(),
        lower_price=body.lower_price,
        upper_price=body.upper_price,
        grid_count=body.grid_count,
        total_capital=body.total_capital,
        take_profit=body.take_profit,
        stop_loss=stop_loss,
        grid_type=body.grid_type,
        trailing_enabled=body.trailing_enabled,
        trailing_offset_pct=body.trailing_offset_pct,
    )
    bot = GridBotEngine(cfg)
    levels = bot.initialize_levels(body.current_price)
    from app.services.bot_risk.grid_sizing import apply_risk_sizing_to_levels

    apply_risk_sizing_to_levels(
        levels,
        total_capital=cfg.total_capital,
        entry_price=body.current_price,
        stop_loss_price=float(stop_loss),
        grid_count=cfg.grid_count,
    )

    bot_id = str(uuid.uuid4())
    summary = bot.get_summary()
    summary["bot_id"] = bot_id

    # Persist: store serialised levels + config
    bots = await _load_all_bots()
    bots[bot_id] = {
        "config": {
            "ticker": cfg.ticker,
            "lower_price": cfg.lower_price,
            "upper_price": cfg.upper_price,
            "grid_count": cfg.grid_count,
            "total_capital": cfg.total_capital,
            "take_profit": cfg.take_profit,
            "stop_loss": cfg.stop_loss,
            "entry_price": body.current_price,
            "grid_type": cfg.grid_type,
            "trailing_enabled": cfg.trailing_enabled,
            "trailing_offset_pct": cfg.trailing_offset_pct,
            "dca_enabled": body.dca_enabled,
            "level_take_profit_pct": body.level_take_profit_pct,
            "level_stop_loss_pct": body.level_stop_loss_pct,
            "level_max_hold_hours": body.level_max_hold_hours,
            "fee_bps": body.fee_bps,
            "slippage_bps": body.slippage_bps,
        },
        "summary": summary,
        "levels": [
            {
                "price": l.price,
                "side": l.side,
                "quantity": l.quantity,
                "status": l.status,
                "fill_price": l.fill_price,
                "pnl": l.pnl,
            }
            for l in bot.state.levels
        ],
        "realized_pnl": bot.state.realized_pnl,
        "total_trades": bot.state.total_trades,
        "is_active": bot.state.is_active,
        "is_paused": False,
        "created_by": email,
        "executor_state": "grid_active",
        "circuit_breaker": {"state": "normal", "allows_new_orders": True},
        "dca_state": {"active": False},
        "barrier_positions": [],
    }
    init_activity_state(bots[bot_id], message=f"Grid bot created for {cfg.ticker}")
    bots[bot_id]["bot_id"] = bot_id

    # Seed live price immediately so UI is not static until Celery beat fires.
    tick_price = body.current_price
    try:
        from app.services.market_data.client import get_grid_tick_quote
        from app.services.market_data.quote_utils import extract_quote_price

        quote = await get_grid_tick_quote(cfg.ticker)
        resolved = extract_quote_price(quote)
        if resolved is not None and resolved > 0:
            tick_price = resolved
    except Exception as exc:
        logger.debug("Grid create live quote fallback", ticker=cfg.ticker, error=str(exc))

    from app.services.grid.tick import apply_price_tick

    bots[bot_id] = apply_price_tick(bots[bot_id], tick_price, bot_id=bot_id)
    await _save_all_bots(bots)

    await audit.log(
        db,
        action=AuditAction.PIPELINE_TRIGGERED,
        details={"event": "grid_bot_created", "bot_id": bot_id, "ticker": cfg.ticker},
    )

    logger.info("Grid bot created", bot_id=bot_id, ticker=cfg.ticker, capital=cfg.total_capital)
    return _summary_out(bot_id, bots[bot_id])


@router.get("/suggest/{ticker}")
async def suggest_grid_params(
    ticker: str,
    email: str = Depends(get_current_user_email),
    risk_level: str = "medium",
    total_capital: float = 10_000.0,
) -> dict[str, float | str | int]:
    """Suggest grid bounds from live quote + realized volatility (AI grid calibration)."""
    from app.services.grid.auto_calibrate import calculate_auto_grid
    from app.services.grid.config import GridType
    from app.services.market_data.client import get_grid_tick_quote

    symbol = ticker.strip().upper()
    if not symbol:
        raise HTTPException(400, "ticker is required")

    try:
        quote = await get_grid_tick_quote(symbol)
    except Exception as exc:
        logger.warning("Grid suggest quote failed", ticker=symbol, error=str(exc))
        raise HTTPException(503, f"Quote unavailable for {symbol}") from exc

    raw_price = quote.get("price")
    if raw_price is None:
        raise HTTPException(503, f"No price returned for {symbol}")

    price = float(raw_price)
    if price <= 0:
        raise HTTPException(503, f"Invalid price for {symbol}")

    closes: list[float] = []
    try:
        from app.db.session import AsyncSessionLocal
        from app.services.market_data.bars import get_bars_for_chart

        async with AsyncSessionLocal() as session:
            bars = await get_bars_for_chart(session, symbol, "1d", 30)
        closes = [float(b.close) for b in bars] if bars else [price]
    except Exception:
        closes = [price]

    rl = risk_level if risk_level in ("low", "medium", "high") else "medium"
    result = calculate_auto_grid(symbol, total_capital, price, closes, risk_level=rl)
    cfg = result.config
    return {
        "ticker": cfg.symbol,
        "current_price": price,
        "lower_price": cfg.lower_bound,
        "upper_price": cfg.upper_bound,
        "stop_loss": cfg.stop_loss or 0.0,
        "take_profit": cfg.take_profit or 0.0,
        "grid_count": cfg.num_levels,
        "grid_type": cfg.grid_type.value,
        "realized_volatility": result.realized_volatility,
        "volatility_regime": result.volatility_regime,
    }


@router.post("/auto-calibrate")
async def auto_calibrate_grid(
    body: AutoCalibrateRequest,
    email: str = Depends(get_current_user_email),
) -> dict[str, Any]:
    """Full auto-calibration response with GridConfig (volatility-based AI grid)."""
    from app.services.grid.auto_calibrate import calculate_auto_grid
    from app.services.grid.config import GridType
    from app.services.market_data.client import get_grid_tick_quote

    symbol = body.ticker.strip().upper()
    try:
        quote = await get_grid_tick_quote(symbol)
    except Exception as exc:
        raise HTTPException(503, f"Quote unavailable for {symbol}") from exc

    price = float(quote.get("price") or 0)
    if price <= 0:
        raise HTTPException(503, f"No price for {symbol}")

    closes: list[float] = []
    try:
        from app.db.session import AsyncSessionLocal
        from app.services.market_data.bars import get_bars_for_chart

        async with AsyncSessionLocal() as session:
            bars = await get_bars_for_chart(session, symbol, "1d", 30)
        closes = [float(b.close) for b in bars] if bars else [price]
    except Exception:
        closes = [price]

    gt = GridType(body.grid_type) if body.grid_type else None
    result = calculate_auto_grid(
        symbol, body.total_capital, price, closes,
        risk_level=body.risk_level,  # type: ignore[arg-type]
        grid_type=gt,
    )
    return {
        "config": result.config.model_dump(),
        "current_price": result.current_price,
        "realized_volatility": result.realized_volatility,
        "volatility_regime": result.volatility_regime,
        "num_levels": result.num_levels,
        "grid_type": result.grid_type.value,
    }


@router.post("/backtest")
async def backtest_grid(
    body: GridBacktestRequest,
    email: str = Depends(get_current_user_email),
    db=Depends(get_db),
) -> dict[str, Any]:
    """Run grid strategy backtest with fees/slippage on historical bars."""
    from app.services.grid.backtest import run_grid_backtest
    from app.services.grid.config import GridConfigModel, GridType

    if body.lower_price >= body.upper_price:
        raise HTTPException(400, "lower_price must be less than upper_price")

    symbol = body.ticker.strip().upper()
    closes: list[float] = []
    try:
        from app.db.session import AsyncSessionLocal
        from app.services.market_data.bars import get_bars_for_chart

        async with AsyncSessionLocal() as session:
            bars = await get_bars_for_chart(session, symbol, "1d", body.bar_limit)
        closes = [float(b.close) for b in bars]
    except Exception as exc:
        raise HTTPException(503, f"Bar history unavailable for {symbol}") from exc

    if len(closes) < 10:
        raise HTTPException(503, f"Insufficient bar history for {symbol}")

    cfg = GridConfigModel(
        symbol=symbol,
        upper_bound=body.upper_price,
        lower_bound=body.lower_price,
        num_levels=body.grid_count,
        grid_type=GridType(body.grid_type),
        capital_allocated=body.total_capital,
        fee_bps=body.fee_bps,
        slippage_bps=body.slippage_bps,
        leverage=body.leverage,
    )
    result = run_grid_backtest(closes, cfg)
    await audit.log(
        db,
        action=AuditAction.PIPELINE_TRIGGERED,
        details={"event": "grid_backtest", "ticker": symbol, "n_trades": result.n_trades},
    )
    return result.to_dict()


@router.get("", response_model=list[GridSummaryOut])
async def list_grid_bots(
    email: str = Depends(get_current_user_email),
) -> list[GridSummaryOut]:
    """List grid bots owned by the current user."""
    bots = await _load_user_bots(email)
    result = [_summary_out(bot_id, data) for bot_id, data in bots.items()]
    return sorted(result, key=lambda b: b.ticker)


@router.get("/bots/{bot_id}/activity", response_model=GridActivityOut)
async def get_grid_bot_activity(
    bot_id: str,
    email: str = Depends(get_current_user_email),
) -> GridActivityOut:
    """Recent fills, pending levels, last tick price, and session P&L for a bot."""
    from app.services.grid.tick import build_activity_payload
    from app.services.portfolio.user_scope import assert_grid_bot_owner

    bots = await _load_all_bots()
    if bot_id not in bots:
        raise HTTPException(404, "Grid bot not found")
    assert_grid_bot_owner(bots[bot_id], email)
    payload = build_activity_payload(bot_id, bots[bot_id])
    return GridActivityOut(**payload)


@router.get("/{bot_id}", response_model=GridSummaryOut)
async def get_grid_bot(
    bot_id: str,
    email: str = Depends(get_current_user_email),
) -> GridSummaryOut:
    """Get a specific grid bot summary."""
    from app.services.portfolio.user_scope import assert_grid_bot_owner

    bots = await _load_all_bots()
    if bot_id not in bots:
        raise HTTPException(404, "Grid bot not found")
    assert_grid_bot_owner(bots[bot_id], email)
    return _summary_out(bot_id, bots[bot_id])


@router.patch("/{bot_id}", response_model=GridSummaryOut)
async def update_grid_bot(
    bot_id: str,
    body: UpdateGridConfigRequest,
    email: str = Depends(get_current_user_email),
) -> GridSummaryOut:
    """Update grid config (grid_count, bounds, capital). Rebuilds levels when no fills yet."""
    from app.services.grid.engine import GridBotEngine, GridConfig
    from app.services.grid.tick import init_activity_state
    from app.services.portfolio.user_scope import assert_grid_bot_owner

    bots = await _load_all_bots()
    if bot_id not in bots:
        raise HTTPException(404, "Grid bot not found")
    assert_grid_bot_owner(bots[bot_id], email)

    data = bots[bot_id]
    if data.get("total_trades", 0) > 0:
        raise HTTPException(
            409,
            "Cannot reconfigure grid after trades have executed. Stop and create a new bot.",
        )

    cfg_data = dict(data.get("config", {}))
    if body.grid_count is not None:
        cfg_data["grid_count"] = body.grid_count
    if body.lower_price is not None:
        cfg_data["lower_price"] = body.lower_price
    if body.upper_price is not None:
        cfg_data["upper_price"] = body.upper_price
    if body.total_capital is not None:
        cfg_data["total_capital"] = body.total_capital

    if cfg_data["lower_price"] >= cfg_data["upper_price"]:
        raise HTTPException(400, "lower_price must be less than upper_price")

    entry_price = float(cfg_data.get("entry_price") or data.get("summary", {}).get("last_price") or 0)
    if entry_price <= 0:
        raise HTTPException(400, "Cannot rebuild grid without a valid entry price")

    cfg = GridConfig(
        ticker=cfg_data["ticker"],
        lower_price=cfg_data["lower_price"],
        upper_price=cfg_data["upper_price"],
        grid_count=cfg_data["grid_count"],
        total_capital=cfg_data["total_capital"],
        take_profit=cfg_data.get("take_profit"),
        stop_loss=cfg_data.get("stop_loss"),
        grid_type=cfg_data.get("grid_type", "geometric"),
        trailing_enabled=bool(cfg_data.get("trailing_enabled", False)),
        trailing_offset_pct=float(cfg_data.get("trailing_offset_pct", 0.02)),
    )
    bot = GridBotEngine(cfg)
    bot.initialize_levels(entry_price)

    data["config"] = cfg_data
    data["levels"] = [
        {
            "price": l.price,
            "side": l.side,
            "quantity": l.quantity,
            "status": l.status,
            "fill_price": l.fill_price,
            "pnl": l.pnl,
        }
        for l in bot.state.levels
    ]
    data["summary"] = bot.get_summary()
    data["summary"]["last_price"] = entry_price
    data["realized_pnl"] = 0.0
    data["total_trades"] = 0
    data["paper_trades"] = []
    init_activity_state(data, message=f"Grid reconfigured ({cfg.grid_count} levels)")
    data["bot_id"] = bot_id
    bots[bot_id] = data
    await _save_all_bots(bots)
    logger.info("Grid bot updated", bot_id=bot_id, grid_count=cfg.grid_count)
    return _summary_out(bot_id, data)


async def _mutate_bot_lifecycle(
    bot_id: str,
    email: str,
    *,
    is_active: bool | None = None,
    is_paused: bool | None = None,
    event_type: str,
    event_message: str,
) -> dict[str, Any]:
    from app.services.grid.tick import _append_event
    from app.services.portfolio.user_scope import assert_grid_bot_owner

    bots = await _load_all_bots()
    if bot_id not in bots:
        raise HTTPException(404, "Grid bot not found")
    assert_grid_bot_owner(bots[bot_id], email)

    data = bots[bot_id]
    if is_active is not None:
        data["is_active"] = is_active
        if not is_active:
            data["is_paused"] = False
    elif is_paused is not None:
        if not data.get("is_active", True):
            raise HTTPException(409, "Cannot pause or resume a stopped bot")
        data["is_paused"] = is_paused

    _append_event(data, event_type, event_message)
    bots[bot_id] = data
    await _save_all_bots(bots)
    return data


@router.post("/{bot_id}/pause", response_model=GridSummaryOut)
async def pause_grid_bot(
    bot_id: str,
    email: str = Depends(get_current_user_email),
) -> GridSummaryOut:
    """Pause fills while keeping the bot and open levels."""
    data = await _mutate_bot_lifecycle(
        bot_id,
        email,
        is_paused=True,
        event_type="paused",
        event_message="Grid bot paused",
    )
    logger.info("Grid bot paused", bot_id=bot_id)
    return _summary_out(bot_id, data)


@router.post("/{bot_id}/resume", response_model=GridSummaryOut)
async def resume_grid_bot(
    bot_id: str,
    email: str = Depends(get_current_user_email),
) -> GridSummaryOut:
    """Resume fills after pause."""
    data = await _mutate_bot_lifecycle(
        bot_id,
        email,
        is_paused=False,
        event_type="resumed",
        event_message="Grid bot resumed",
    )
    logger.info("Grid bot resumed", bot_id=bot_id)
    return _summary_out(bot_id, data)


@router.post("/{bot_id}/stop", response_model=GridSummaryOut)
async def halt_grid_bot(
    bot_id: str,
    email: str = Depends(get_current_user_email),
    db=Depends(get_db),
) -> GridSummaryOut:
    """Stop trading (soft stop — bot remains visible with history)."""
    data = await _mutate_bot_lifecycle(
        bot_id,
        email,
        is_active=False,
        event_type="stopped",
        event_message="Grid bot stopped",
    )
    await audit.log(
        db,
        action=AuditAction.MANEUVER_CANCELLED,
        details={"event": "grid_bot_halted", "bot_id": bot_id},
    )
    logger.info("Grid bot halted (soft stop)", bot_id=bot_id)
    return _summary_out(bot_id, data)


@router.delete("/{bot_id}", status_code=status.HTTP_200_OK)
async def stop_grid_bot(
    bot_id: str,
    email: str = Depends(get_current_user_email),
    db=Depends(get_db),
) -> None:
    """Stop and remove a grid bot."""
    from app.services.portfolio.user_scope import assert_grid_bot_owner

    bots = await _load_all_bots()
    if bot_id not in bots:
        raise HTTPException(404, "Grid bot not found")
    assert_grid_bot_owner(bots[bot_id], email)
    del bots[bot_id]
    await _save_all_bots(bots)
    await audit.log(
        db,
        action=AuditAction.MANEUVER_CANCELLED,
        details={"event": "grid_bot_stopped", "bot_id": bot_id},
    )
    logger.info("Grid bot stopped", bot_id=bot_id)


@router.post("/{bot_id}/price", response_model=GridSummaryOut)
async def update_bot_price(
    bot_id: str,
    price: float,
    email: str = Depends(get_current_user_email),
) -> GridSummaryOut:
    """
    Notify the bot of the current market price.
    Triggers fill simulation and PnL update.
    Used in paper mode — Celery tick task also drives this automatically.
    """
    from app.services.grid.tick import apply_price_tick
    from app.services.portfolio.user_scope import assert_grid_bot_owner

    bots = await _load_all_bots()
    if bot_id not in bots:
        raise HTTPException(404, "Grid bot not found")
    assert_grid_bot_owner(bots[bot_id], email)

    data = apply_price_tick(bots[bot_id], price, bot_id=bot_id)
    bots[bot_id] = data
    await _save_all_bots(bots)
    return _summary_out(bot_id, data)
