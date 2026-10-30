"""Unified bot catalog: Postgres row + existing Redis runtimes.

Prompt 27: paper fills for the new path go through bot_core into the book.
This Redis runtime stays until a later cut (not deleted on 2026-10-07).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select

from app.core.logging import get_logger
from app.db.bot_models import Bot, BotStatus, BotType
from app.services.bots.common import build_summary, init_activity_state
from app.services.bots.dca import apply_dca_tick, new_runtime as new_dca_runtime
from app.services.bots.momentum import apply_momentum_tick, new_runtime as new_mom_runtime
from app.services.bots.store import assert_bot_owner, load_bots, load_user_bots, save_bots

logger = get_logger(__name__)

BOT_TYPES = (BotType.GRID.value, BotType.DCA.value, BotType.MOMENTUM.value)
STATUSES = (BotStatus.ACTIVE.value, BotStatus.PAUSED.value, BotStatus.STOPPED.value)

_GRID_KEY = "grid:bots"
_DCA_KEY = "dca:bots"
_MOMENTUM_KEY = "momentum:bots"

_memory: dict[str, dict[str, dict]] = {
    BotType.GRID.value: {},
    BotType.DCA.value: {},
    BotType.MOMENTUM.value: {},
}

_KEYS = {
    BotType.GRID.value: _GRID_KEY,
    BotType.DCA.value: _DCA_KEY,
    BotType.MOMENTUM.value: _MOMENTUM_KEY,
}


def runtime_status(data: dict[str, Any]) -> str:
    if not data.get("is_active", True):
        return BotStatus.STOPPED.value
    if data.get("is_paused"):
        return BotStatus.PAUSED.value
    return BotStatus.ACTIVE.value


def apply_status(data: dict[str, Any], status_value: str) -> None:
    if status_value == BotStatus.STOPPED.value:
        data["is_active"] = False
        return
    if status_value == BotStatus.PAUSED.value:
        data["is_active"] = True
        data["is_paused"] = True
        return
    if status_value == BotStatus.ACTIVE.value:
        data["is_active"] = True
        data["is_paused"] = False
        return
    raise HTTPException(400, f"status must be one of: {', '.join(STATUSES)}")


def _num(params: dict[str, Any], *names: str, default: float | None = None) -> float | None:
    for name in names:
        if name in params and params[name] is not None and params[name] != "":
            return float(params[name])
    return default


def _int(params: dict[str, Any], *names: str, default: int | None = None) -> int | None:
    for name in names:
        if name in params and params[name] is not None and params[name] != "":
            return int(params[name])
    return default


async def _resolve_price(symbol: str, fallback: float | None) -> float:
    try:
        from app.services.market_data.client import get_grid_tick_quote
        from app.services.market_data.quote_utils import extract_quote_price

        quote = await get_grid_tick_quote(symbol)
        resolved = extract_quote_price(quote)
        if resolved and resolved > 0:
            return float(resolved)
    except Exception as exc:
        logger.debug("unified bot quote fallback", symbol=symbol, error=str(exc))
    if fallback is not None and fallback > 0:
        return float(fallback)
    raise HTTPException(400, "current_price is required when no live quote is available")


def _normalize_params(bot_type: str, symbol: str, params: dict[str, Any], capital: float) -> dict[str, Any]:
    raw = dict(params or {})
    if bot_type == BotType.GRID.value:
        lower = _num(raw, "lower_price", "lower")
        upper = _num(raw, "upper_price", "upper")
        grid_count = _int(raw, "grid_count")
        if lower is None or upper is None or grid_count is None:
            raise HTTPException(400, "grid params require lower_price, upper_price, grid_count")
        if lower >= upper:
            raise HTTPException(400, "lower_price must be less than upper_price")
        if grid_count < 2:
            raise HTTPException(400, "grid_count must be >= 2")
        return {
            "ticker": symbol,
            "lower_price": lower,
            "upper_price": upper,
            "grid_count": grid_count,
            "total_capital": capital,
            "current_price": _num(raw, "current_price", "entry_price"),
        }
    if bot_type == BotType.DCA.value:
        interval = _int(raw, "interval_ticks", "interval", default=5)
        dip = _num(raw, "dip_pct", "drawdown_pct", default=0.02)
        if dip is not None and dip > 1:
            dip = dip / 100.0
        return {
            "ticker": symbol,
            "total_capital": capital,
            "order_size_usd": _num(raw, "order_size_usd", default=500.0),
            "max_entries": _int(raw, "max_entries", default=10),
            "interval_ticks": interval,
            "dip_pct": dip,
            "take_profit_pct": _num(raw, "take_profit_pct", default=0.05),
            "current_price": _num(raw, "current_price", "entry_price"),
        }
    if bot_type == BotType.MOMENTUM.value:
        threshold = _num(raw, "entry_momentum_pct", "threshold", default=0.03)
        size = _num(raw, "position_size_pct", "size", default=0.5)
        if threshold is not None and threshold > 1:
            threshold = threshold / 100.0
        if size is not None and size > 1:
            size = size / 100.0
        return {
            "ticker": symbol,
            "total_capital": capital,
            "position_size_pct": size,
            "lookback_ticks": _int(raw, "lookback_ticks", default=20),
            "entry_momentum_pct": threshold,
            "take_profit_pct": _num(raw, "take_profit_pct", default=0.06),
            "stop_loss_pct": _num(raw, "stop_loss_pct", default=0.04),
            "current_price": _num(raw, "current_price", "entry_price"),
        }
    raise HTTPException(400, f"bot_type must be one of: {', '.join(BOT_TYPES)}")


async def _create_grid_runtime(email: str, params: dict[str, Any], price: float) -> tuple[str, dict[str, Any]]:
    try:
        from app.services.grid.engine import GridBotEngine, GridConfig
        from app.services.grid.tick import apply_price_tick, init_activity_state as init_grid_activity
    except Exception as exc:
        raise HTTPException(503, "Grid engine unavailable") from exc

    cfg = GridConfig(
        ticker=params["ticker"],
        lower_price=params["lower_price"],
        upper_price=params["upper_price"],
        grid_count=params["grid_count"],
        total_capital=params["total_capital"],
        take_profit=None,
        stop_loss=None,
        grid_type="geometric",
        trailing_enabled=False,
        trailing_offset_pct=0.02,
    )
    engine = GridBotEngine(cfg)
    engine.initialize_levels(price)
    bot_id = str(uuid.uuid4())
    summary = engine.get_summary()
    summary["bot_id"] = bot_id
    record: dict[str, Any] = {
        "config": {
            "ticker": cfg.ticker,
            "lower_price": cfg.lower_price,
            "upper_price": cfg.upper_price,
            "grid_count": cfg.grid_count,
            "total_capital": cfg.total_capital,
            "take_profit": cfg.take_profit,
            "stop_loss": cfg.stop_loss,
            "entry_price": price,
            "grid_type": getattr(cfg, "grid_type", "geometric"),
            "trailing_enabled": False,
            "trailing_offset_pct": 0.02,
        },
        "summary": summary,
        "levels": [
            {
                "price": level.price,
                "side": level.side,
                "quantity": level.quantity,
                "status": level.status,
                "fill_price": level.fill_price,
                "pnl": level.pnl,
            }
            for level in engine.state.levels
        ],
        "realized_pnl": engine.state.realized_pnl,
        "total_trades": engine.state.total_trades,
        "is_active": engine.state.is_active,
        "is_paused": False,
        "created_by": email,
        "executor_state": "grid_active",
        "bot_id": bot_id,
    }
    init_grid_activity(record, message=f"Grid bot created for {cfg.ticker}")
    record = apply_price_tick(record, price, bot_id=bot_id)
    return bot_id, record


async def _create_dca_runtime(email: str, params: dict[str, Any], price: float) -> tuple[str, dict[str, Any]]:
    if float(params["order_size_usd"]) * int(params["max_entries"]) > float(params["total_capital"]) + 1e-6:
        raise HTTPException(400, "order_size_usd * max_entries exceeds total_capital")
    bot_id = str(uuid.uuid4())
    record: dict[str, Any] = {
        "config": {k: v for k, v in params.items() if k != "current_price"} | {"entry_price": price},
        "runtime": new_dca_runtime(price),
        "realized_pnl": 0.0,
        "unrealized_pnl": 0.0,
        "total_pnl": 0.0,
        "total_trades": 0,
        "is_active": True,
        "is_paused": False,
        "created_by": email,
        "bot_id": bot_id,
    }
    init_activity_state(record, message=f"DCA bot created for {params['ticker']}")
    record = apply_dca_tick(record, price, bot_id=bot_id)
    return bot_id, record


async def _create_momentum_runtime(email: str, params: dict[str, Any], price: float) -> tuple[str, dict[str, Any]]:
    bot_id = str(uuid.uuid4())
    record: dict[str, Any] = {
        "config": {k: v for k, v in params.items() if k != "current_price"} | {"entry_price": price},
        "runtime": new_mom_runtime(price),
        "realized_pnl": 0.0,
        "unrealized_pnl": 0.0,
        "total_pnl": 0.0,
        "total_trades": 0,
        "is_active": True,
        "is_paused": False,
        "created_by": email,
        "bot_id": bot_id,
    }
    init_activity_state(record, message=f"Momentum bot created for {params['ticker']}")
    record = apply_momentum_tick(record, price, bot_id=bot_id)
    return bot_id, record


def _to_out(bot_type: str, bot_id: str, data: dict[str, Any], catalog: Bot | None = None) -> dict[str, Any]:
    cfg = data.get("config") or {}
    if bot_type == BotType.GRID.value:
        summary = data.get("summary") or {}
        symbol = summary.get("ticker") or cfg.get("ticker") or (catalog.symbol if catalog else "")
        trades = int(data.get("total_trades") or summary.get("total_trades") or (catalog.total_trades if catalog else 0) or 0)
        pnl = float(
            data.get("total_pnl")
            if data.get("total_pnl") is not None
            else (
                float(data.get("realized_pnl") or 0.0)
                + float(summary.get("unrealized_pnl") or 0.0)
            )
        )
        capital = float(cfg.get("total_capital") or (catalog.balance_allocated if catalog else 0.0) or 0.0)
        params = {
            "lower_price": cfg.get("lower_price"),
            "upper_price": cfg.get("upper_price"),
            "grid_count": cfg.get("grid_count"),
        }
    else:
        summary = build_summary(bot_id, data)
        symbol = summary.get("ticker") or cfg.get("ticker") or (catalog.symbol if catalog else "")
        trades = int(summary.get("total_trades") or 0)
        pnl = float(summary.get("total_pnl") or 0.0)
        capital = float(summary.get("total_capital") or 0.0)
        if bot_type == BotType.DCA.value:
            params = {
                "interval_ticks": cfg.get("interval_ticks"),
                "dip_pct": cfg.get("dip_pct"),
            }
        else:
            params = {
                "entry_momentum_pct": cfg.get("entry_momentum_pct"),
                "position_size_pct": cfg.get("position_size_pct"),
            }
    created_at = None
    if catalog is not None and catalog.created_at is not None:
        created_at = catalog.created_at.isoformat()
    return {
        "id": bot_id,
        "bot_type": bot_type,
        "symbol": str(symbol).upper(),
        "status": runtime_status(data) if data else (catalog.status if catalog else BotStatus.STOPPED.value),
        "params": params,
        "total_trades": trades,
        "pnl": round(pnl, 4),
        "balance_allocated": capital,
        "created_at": created_at,
    }


async def _persist(db: Any, row: Bot) -> None:
    if db is None:
        return
    try:
        existing = await db.get(Bot, row.id)
        if existing is None:
            db.add(row)
        else:
            existing.bot_type = row.bot_type
            existing.symbol = row.symbol
            existing.status = row.status
            existing.params = row.params
            existing.total_trades = row.total_trades
            existing.pnl = row.pnl
            existing.balance_allocated = row.balance_allocated
            if row.user_id and not existing.user_id:
                existing.user_id = row.user_id
        await db.commit()
    except Exception as exc:
        logger.warning("bots catalog persist failed", error=str(exc), bot_id=row.id)
        try:
            await db.rollback()
        except Exception:
            raise


async def _load_catalog(db: Any, email: str) -> dict[str, Bot]:
    if db is None:
        return {}
    try:
        result = await db.execute(select(Bot).where(Bot.created_by == email))
        return {row.id: row for row in result.scalars().all()}
    except Exception as exc:
        logger.debug("bots catalog read failed", error=str(exc))
        return {}


async def create_bot(
    *,
    db: Any,
    email: str,
    user_id: str | None,
    bot_type: str,
    symbol: str,
    params: dict[str, Any],
    balance_allocated: float,
) -> dict[str, Any]:
    kind = (bot_type or "").strip().lower()
    if kind not in BOT_TYPES:
        raise HTTPException(400, f"bot_type must be one of: {', '.join(BOT_TYPES)}")
    if balance_allocated <= 0:
        raise HTTPException(400, "balance_allocated must be > 0")
    ticker = (symbol or "").strip().upper()
    if not ticker:
        raise HTTPException(400, "symbol is required")

    normalized = _normalize_params(kind, ticker, params, balance_allocated)
    price = await _resolve_price(ticker, normalized.get("current_price"))

    if kind == BotType.GRID.value:
        from app.services.portfolio.capital_overlap import maneuver_occupied_tickers_for_email

        locked = await maneuver_occupied_tickers_for_email(db, email)
        if ticker in locked:
            raise HTTPException(
                400,
                f"Тикер {ticker} уже в открытом манёвре — сетку не открываем (один капитал).",
            )
        from app.services.forecast.daily_book import score_20_for_symbol

        beat_score = score_20_for_symbol(ticker)
        if beat_score is not None and beat_score <= 3:
            raise HTTPException(
                400,
                f"Скор {ticker} = {beat_score}/10 — сетку не открываем на слабом ранге.",
            )
        bot_id, record = await _create_grid_runtime(email, normalized, price)
    elif kind == BotType.DCA.value:
        bot_id, record = await _create_dca_runtime(email, normalized, price)
    else:
        bot_id, record = await _create_momentum_runtime(email, normalized, price)

    all_bots = await load_bots(_KEYS[kind], _memory[kind])
    all_bots[bot_id] = record
    await save_bots(_KEYS[kind], _memory[kind], all_bots)

    out = _to_out(kind, bot_id, record)
    await _persist(
        db,
        Bot(
            id=bot_id,
            user_id=user_id,
            created_by=email,
            bot_type=kind,
            symbol=out["symbol"],
            status=out["status"],
            params=out["params"],
            total_trades=out["total_trades"],
            pnl=out["pnl"],
            balance_allocated=out["balance_allocated"],
            created_at=datetime.now(timezone.utc),
        ),
    )
    try:
        from app.services.forecast_log.emit import emit_bot_or_composer

        emit_bot_or_composer(
            ticker=str(out.get("symbol") or ticker),
            direction=0,
            probability="0.5",
            section="bots",
            model_id=f"bot_{kind}",
        )
    except Exception:
        raise
    return out


async def list_bots(*, db: Any, email: str, bot_type: str | None = None) -> list[dict[str, Any]]:
    kind_filter = (bot_type or "").strip().lower() or None
    if kind_filter and kind_filter not in BOT_TYPES:
        raise HTTPException(400, f"bot_type must be one of: {', '.join(BOT_TYPES)}")

    catalog = await _load_catalog(db, email)
    seen: set[str] = set()
    items: list[dict[str, Any]] = []

    kinds = (kind_filter,) if kind_filter else BOT_TYPES
    for kind in kinds:
        runtime = await load_user_bots(_KEYS[kind], _memory[kind], email)
        for bot_id, data in runtime.items():
            seen.add(bot_id)
            row = catalog.get(bot_id)
            out = _to_out(kind, bot_id, data, row)
            items.append(out)
            if row is None:
                await _persist(
                    db,
                    Bot(
                        id=bot_id,
                        user_id=None,
                        created_by=email,
                        bot_type=kind,
                        symbol=out["symbol"],
                        status=out["status"],
                        params=out["params"],
                        total_trades=out["total_trades"],
                        pnl=out["pnl"],
                        balance_allocated=out["balance_allocated"],
                    ),
                )

    for bot_id, row in catalog.items():
        if bot_id in seen:
            continue
        if kind_filter and row.bot_type != kind_filter:
            continue
        items.append({
            "id": row.id,
            "bot_type": row.bot_type,
            "symbol": row.symbol,
            "status": row.status,
            "params": row.params or {},
            "total_trades": row.total_trades,
            "pnl": row.pnl,
            "balance_allocated": row.balance_allocated,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        })

    items.sort(key=lambda item: ((item.get("created_at") or ""), item["id"]), reverse=True)
    return items


async def _find_runtime(bot_id: str, email: str) -> tuple[str, dict[str, Any]] | None:
    for kind in BOT_TYPES:
        bots = await load_user_bots(_KEYS[kind], _memory[kind], email)
        data = bots.get(bot_id)
        if data:
            assert_bot_owner(data, email)
            return kind, data
    return None


async def get_bot(*, db: Any, email: str, bot_id: str) -> dict[str, Any]:
    found = await _find_runtime(bot_id, email)
    catalog = await _load_catalog(db, email)
    row = catalog.get(bot_id)
    if found:
        kind, data = found
        return _to_out(kind, bot_id, data, row)
    if row and row.created_by.lower() == email.lower():
        return {
            "id": row.id,
            "bot_type": row.bot_type,
            "symbol": row.symbol,
            "status": row.status,
            "params": row.params or {},
            "total_trades": row.total_trades,
            "pnl": row.pnl,
            "balance_allocated": row.balance_allocated,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Bot not found")


async def patch_bot(
    *,
    db: Any,
    email: str,
    user_id: str | None,
    bot_id: str,
    status_value: str | None,
    params: dict[str, Any] | None,
) -> dict[str, Any]:
    found = await _find_runtime(bot_id, email)
    if not found:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bot not found")
    kind, data = found
    if status_value is not None:
        apply_status(data, status_value.strip().lower())
    if params:
        cfg = data.setdefault("config", {})
        normalized = _normalize_params(
            kind,
            str(cfg.get("ticker") or ""),
            {**cfg, **params},
            float(cfg.get("total_capital") or 1),
        )
        if kind == BotType.GRID.value and int(data.get("total_trades") or 0) > 0:
            raise HTTPException(400, "grid params cannot change after the first trade")
        for key in ("lower_price", "upper_price", "grid_count", "interval_ticks", "dip_pct", "entry_momentum_pct", "position_size_pct"):
            if key in normalized and normalized[key] is not None:
                cfg[key] = normalized[key]
    all_bots = await load_bots(_KEYS[kind], _memory[kind])
    all_bots[bot_id] = data
    await save_bots(_KEYS[kind], _memory[kind], all_bots)
    out = _to_out(kind, bot_id, data)
    await _persist(
        db,
        Bot(
            id=bot_id,
            user_id=user_id,
            created_by=email,
            bot_type=kind,
            symbol=out["symbol"],
            status=out["status"],
            params=out["params"],
            total_trades=out["total_trades"],
            pnl=out["pnl"],
            balance_allocated=out["balance_allocated"],
        ),
    )
    return out


async def delete_bot(*, db: Any, email: str, bot_id: str) -> None:
    found = await _find_runtime(bot_id, email)
    if found:
        kind, _data = found
        all_bots = await load_bots(_KEYS[kind], _memory[kind])
        if bot_id in all_bots:
            assert_bot_owner(all_bots[bot_id], email)
            del all_bots[bot_id]
            await save_bots(_KEYS[kind], _memory[kind], all_bots)
    if db is not None:
        try:
            row = await db.get(Bot, bot_id)
            if row is not None:
                if (row.created_by or "").lower() != email.lower():
                    raise HTTPException(status.HTTP_404_NOT_FOUND, "Bot not found")
                await db.delete(row)
                await db.commit()
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("bots catalog delete failed", error=str(exc), bot_id=bot_id)
            try:
                await db.rollback()
            except Exception:
                raise
    if not found:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bot not found")
