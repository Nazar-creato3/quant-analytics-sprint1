"""Agentic tool layer for in-app chat — wraps existing backend services as callable tools."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger

logger = get_logger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stamp(tool: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Attach tool identity + freshness; mark missing data so the LLM cannot fabricate."""
    out = dict(payload)
    out["tool"] = tool
    out["tool_called_at"] = _utc_now()
    if "data_as_of" not in out or not out.get("data_as_of"):
        out["data_as_of"] = out.get("as_of") or out["tool_called_at"]
    failed = bool(
        out.get("error")
        or out.get("insufficient_data")
        or out.get("validation_failed")
        or out.get("data_available") is False
    )
    if failed:
        out["data_available"] = False
        out["fabrication_forbidden"] = True
        out.setdefault(
            "assistant_instruction",
            "Скажи пользователю, что данных нет или расчёт не удался. Не выдумывай цифры.",
        )
    else:
        out.setdefault("data_available", True)
    return out

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_factor_exposures",
            "description": "Get factor model exposures (Value, Momentum, Quality, etc.) for a ticker",
            "parameters": {
                "type": "object",
                "properties": {"ticker": {"type": "string", "description": "Ticker symbol"}},
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_shap_explanation",
            "description": "Get SHAP feature attribution for the ML score of a ticker",
            "parameters": {
                "type": "object",
                "properties": {"ticker": {"type": "string"}},
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_risk_metrics",
            "description": "Get VaR, CVaR, Sharpe, max drawdown for a ticker",
            "parameters": {
                "type": "object",
                "properties": {"ticker": {"type": "string"}},
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_recent_news",
            "description": "Get recent news headlines for a ticker from the RSS pipeline",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "days_back": {"type": "integer", "default": 7},
                },
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_tickers",
            "description": "Side-by-side factor/risk comparison for 2+ tickers",
            "parameters": {
                "type": "object",
                "properties": {
                    "tickers": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 2,
                    }
                },
                "required": ["tickers"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_market_regime",
            "description": "Current market regime classification (trending/range-bound/high-vol)",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_dividend_data",
            "description": "Get dividend history and trailing yield for a ticker (MOEX ISS / yfinance)",
            "parameters": {
                "type": "object",
                "properties": {"ticker": {"type": "string"}},
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_portfolio_returns",
            "description": "TWR (decision return) and MWR (money growth) from the portfolio book",
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {"type": "string", "default": "paper"},
                    "period": {"type": "string", "default": "inception"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_macro_context",
            "description": "Current key rate, FX rates, relevant macro indicators",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_forecast_distribution",
            "description": (
                "Get point forecast, signal strength, and full quantile interval for a ticker, "
                "derived from one consistent model output"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "horizon": {"type": "string", "default": "10d"},
                },
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_rolling_accuracy",
            "description": (
                "Get walk-forward regime classification accuracy per evaluation window "
                "(regime_match_accuracy — label match, not price up/down direction), "
                "alongside calibration error (MAE) for that window"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "window": {"type": "string", "default": "all"},
                },
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_correlation_matrix",
            "description": "Get validated pairwise correlation matrix for a set of tickers",
            "parameters": {
                "type": "object",
                "properties": {
                    "tickers": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 2,
                    }
                },
                "required": ["tickers"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_forecast",
            "description": (
                "Get the platform's current forecast for a symbol with honesty/suppression "
                "flags. Never invent numbers if the tool says data is suppressed or invalid."
            ),
            "parameters": {
                "type": "object",
                "properties": {"ticker": {"type": "string"}},
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_portfolio_risk_metrics",
            "description": (
                "Get the user's current portfolio risk pack: historical VaR 95/99, "
                "sector concentration, alpha/beta vs SPY, correlation, stress tests."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_position_pnl",
            "description": "Get current mark-to-market P&L for an open position or the whole book",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "Optional ticker; omit for the full book",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_instruments",
            "description": "Search the universal instrument registry by symbol substring",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Symbol or prefix, e.g. AAP or SBER"},
                },
                "required": ["query"],
            },
        },
    },
]


async def _resolve_ticker(db: AsyncSession, ticker: str):
    from app.services.instrument.resolver import resolve_or_create_instrument

    return await resolve_or_create_instrument(db, ticker.strip().upper())


async def execute_tool(
    db: AsyncSession,
    name: str,
    arguments: dict[str, Any],
    *,
    owner_user_id: str | None = None,
    owner_email: str | None = None,
) -> str:
    """Execute a named tool and return JSON string result."""
    from app.services.forecast.numeric_integrity import apply_validation_to_payload

    if name in {"place_order", "create_order", "execute_order", "submit_order"}:
        return json.dumps({"error": "chat_cannot_create_orders", "data_available": False})
    if name.startswith("qa_"):
        from app.services.chat.qa_registry import invoke

        if not owner_user_id:
            return json.dumps({"error": "owner_required", "data_available": False})
        return json.dumps(invoke(name=name, user_id=owner_user_id, ticker=arguments.get("ticker")))
    validated_tools = {
        "get_forecast_distribution",
        "get_current_forecast",
        "get_rolling_accuracy",
        "get_correlation_matrix",
        "get_market_regime",
        "get_risk_metrics",
        "get_portfolio_risk_metrics",
    }
    try:
        if name == "get_factor_exposures":
            payload = await _tool_factor_exposures(db, arguments["ticker"])
        elif name == "get_shap_explanation":
            payload = await _tool_shap(db, arguments["ticker"])
        elif name == "get_risk_metrics":
            payload = await _tool_risk(db, arguments["ticker"])
        elif name == "get_recent_news":
            days = int(arguments.get("days_back", 7))
            payload = await _tool_news(db, arguments["ticker"], days)
        elif name == "compare_tickers":
            payload = await _tool_compare(db, arguments["tickers"])
        elif name == "get_market_regime":
            payload = await _tool_market_regime(db)
        elif name == "get_dividend_data":
            payload = await _tool_dividends(db, arguments["ticker"])
        elif name == "get_macro_context":
            payload = await _tool_macro(db)
        elif name == "get_forecast_distribution":
            payload = await _tool_forecast_distribution(
                db,
                arguments["ticker"],
                horizon=str(arguments.get("horizon", "10d")),
            )
        elif name == "get_current_forecast":
            payload = await _tool_current_forecast(db, arguments["ticker"])
        elif name == "get_rolling_accuracy":
            payload = await _tool_rolling_accuracy(
                db,
                arguments["ticker"],
                window=str(arguments.get("window", "all")),
            )
        elif name == "get_correlation_matrix":
            payload = await _tool_correlation_matrix(db, arguments["tickers"])
        elif name == "get_portfolio_risk_metrics":
            payload = await _tool_portfolio_risk(db, owner_user_id=owner_user_id, owner_email=owner_email)
        elif name == "get_position_pnl":
            payload = await _tool_position_pnl(
                db,
                ticker=str(arguments.get("ticker") or "") or None,
                owner_user_id=owner_user_id,
                owner_email=owner_email,
            )
        elif name == "get_portfolio_returns":
            from app.services.returns.service import as_dict, compute_returns

            payload = as_dict(
                compute_returns(
                    user_id=owner_user_id or owner_email or "system",
                    mode=str(arguments.get("mode") or "paper"),
                    period=str(arguments.get("period") or "inception"),  # type: ignore[arg-type]
                )
            )
        elif name == "search_instruments":
            payload = await _tool_search_instruments(db, str(arguments.get("query") or ""))
        else:
            return json.dumps(_stamp(name, {"error": f"unknown tool: {name}", "data_available": False}))

        if name in validated_tools:
            payload = apply_validation_to_payload(name, payload)
        return json.dumps(_stamp(name, payload), ensure_ascii=False)
    except Exception as exc:
        logger.warning("Tool execution failed", tool=name, error=str(exc))
        return json.dumps(_stamp(name, {"error": str(exc), "data_available": False}))


async def _tool_factor_exposures(db: AsyncSession, ticker: str) -> dict[str, Any]:
    from app.services.analysis.context import gather_analysis_context
    from app.services.prediction_hierarchy.orchestrator import get_hierarchy_orchestrator

    instrument = await _resolve_ticker(db, ticker)
    hierarchy = await get_hierarchy_orchestrator().get_forecast(
        db, instrument.id, symbol=instrument.symbol, include_narrative=False
    )
    ctx = await gather_analysis_context(
        db, instrument_id=instrument.id, symbol=instrument.symbol, output=hierarchy
    )
    factors = ctx.factor_exposures or {}
    if ctx.ticker_analysis and ctx.ticker_analysis.factor_exposures:
        factors = {**factors, **ctx.ticker_analysis.factor_exposures}
    return {"ticker": instrument.symbol, "factor_exposures": factors}


async def _tool_shap(db: AsyncSession, ticker: str) -> dict[str, Any]:
    from app.services.analysis.context import gather_analysis_context
    from app.services.analysis.ticker_payload import assemble_ticker_analysis_payload
    from app.services.prediction_hierarchy.orchestrator import get_hierarchy_orchestrator

    instrument = await _resolve_ticker(db, ticker)
    hierarchy = await get_hierarchy_orchestrator().get_forecast(
        db, instrument.id, symbol=instrument.symbol, include_narrative=False
    )
    ctx = await gather_analysis_context(
        db, instrument_id=instrument.id, symbol=instrument.symbol, output=hierarchy
    )
    payload = assemble_ticker_analysis_payload(output=hierarchy, analysis=ctx)
    return {
        "ticker": instrument.symbol,
        "ml_score": payload.ml_score,
        "shap_top_factors": [
            {"feature": f.feature, "impact": f.impact} for f in (payload.shap_top_factors or [])
        ],
    }


async def _tool_risk(db: AsyncSession, ticker: str) -> dict[str, Any]:
    from app.services.qa.feature_flags import is_enabled
    from app.services.risk_engine.series import get_series
    from app.services.risk_engine.service import as_dict, compute_risk

    if not is_enabled("qa_risk_engine"):
        return {"ticker": ticker.upper(), "data_status": "флаг выключен", "risk_metrics": None}
    series = get_series(ticker)
    if not series:
        return {"ticker": ticker.upper(), "data_status": "нет данных", "risk_metrics": None}
    return {"ticker": ticker.upper(), "risk_metrics": as_dict(compute_risk(series, tickers=[ticker]))}


async def _tool_news(db: AsyncSession, ticker: str, days_back: int) -> dict[str, Any]:
    from app.services.analysis.context import gather_analysis_context
    from app.services.analysis.ticker_payload import assemble_ticker_analysis_payload
    from app.services.prediction_hierarchy.orchestrator import get_hierarchy_orchestrator

    instrument = await _resolve_ticker(db, ticker)
    hierarchy = await get_hierarchy_orchestrator().get_forecast(
        db, instrument.id, symbol=instrument.symbol, include_narrative=False
    )
    ctx = await gather_analysis_context(
        db, instrument_id=instrument.id, symbol=instrument.symbol, output=hierarchy
    )
    payload = assemble_ticker_analysis_payload(output=hierarchy, analysis=ctx)
    titles = payload.news_titles or []
    return {
        "ticker": instrument.symbol,
        "days_back": days_back,
        "headlines": titles[:20],
        "count": len(titles),
    }


async def _tool_compare(db: AsyncSession, tickers: list[str]) -> dict[str, Any]:
    results = []
    for t in tickers[:5]:
        try:
            factors = await _tool_factor_exposures(db, t)
            risk = await _tool_risk(db, t)
            results.append(
                {
                    "ticker": t.upper(),
                    "factor_exposures": factors.get("factor_exposures", {}),
                    "risk_metrics": risk.get("risk_metrics", {}),
                }
            )
        except Exception as exc:
            results.append({"ticker": t.upper(), "error": str(exc)})
    return {"comparison": results}


async def _tool_market_regime(db: AsyncSession) -> dict[str, Any]:
    from app.services.qa.feature_flags import is_enabled
    from app.services.market_regime.service import snapshot

    if is_enabled("qa_market_regime"):
        return snapshot(ticker="IMOEX")

    from app.services.forecast.market_forecast import build_market_forecast

    payload = await build_market_forecast(db)
    return {
        "global_regime": payload.get("global_regime", {}),
        "sector_rotation": payload.get("sector_rotation", []),
    }


async def _tool_dividends(db: AsyncSession, ticker: str) -> dict[str, Any]:
    from app.services.market_data.enrichment import fetch_fundamentals
    from app.services.market_data.moex_iss_provider import fetch_moex_dividends
    from app.services.market_data.moex_spot import is_moex_ticker

    instrument = await _resolve_ticker(db, ticker)
    sym = instrument.symbol
    payload: dict[str, Any] = {"ticker": sym}

    if is_moex_ticker(sym):
        moex_div = await fetch_moex_dividends(sym)
        payload.update(moex_div)

    fund = await fetch_fundamentals(sym)
    if fund.get("dividend_yield") is not None:
        payload["dividend_yield"] = fund["dividend_yield"]
    if fund.get("dividend_history"):
        payload.setdefault("dividends", fund["dividend_history"])
    payload["fundamentals_source"] = fund.get("source")
    if not payload.get("dividends") and not payload.get("dividend_yield"):
        payload["note"] = "Dividend data unavailable from connected sources"
    return payload


async def _tool_macro(db: AsyncSession) -> dict[str, Any]:
    from app.services.macro_registry.service import load_macro_snapshot

    indicators = await load_macro_snapshot(db)
    keys = ("rate_cb", "cpi", "vix", "dxy", "oil_brent", "unemployment", "credit_spread")
    return {"indicators": {k: indicators[k] for k in keys if k in indicators}}


async def _tool_forecast_distribution(
    db: AsyncSession,
    ticker: str,
    *,
    horizon: str = "10d",
) -> dict[str, Any]:
    from app.services.forecast.distribution import build_forecast_distribution
    from app.services.market_data.series_loader import load_forecast_price_series
    from app.services.prediction_hierarchy.orchestrator import get_hierarchy_orchestrator

    instrument = await _resolve_ticker(db, ticker)
    hierarchy = await get_hierarchy_orchestrator().get_forecast(
        db, instrument.id, symbol=instrument.symbol, include_narrative=False
    )
    prices, _, _src = await load_forecast_price_series(
        db, instrument.id, instrument.symbol, persist=False
    )
    signals = hierarchy.raw_ticker_confidence  # fallback
    momentum = hierarchy.point_forecast.momentum_score if hierarchy.point_forecast else 0.5
    from app.services.forecast.types import ForecastDirection

    direction = ForecastDirection.NEUTRAL
    if hierarchy.point_forecast:
        sign = hierarchy.point_forecast.expected_return_sign
        if sign > 0:
            direction = ForecastDirection.BULLISH
        elif sign < 0:
            direction = ForecastDirection.BEARISH

    dist = build_forecast_distribution(
        prices=prices,
        momentum_score=momentum,
        direction=direction,
    )
    payload = dist.to_dict()
    payload["ticker"] = instrument.symbol
    payload["horizon"] = horizon
    payload["calibrated_confidence"] = hierarchy.calibrated_confidence
    from app.services.forecast.probability_map import build_metric_validity

    payload["metric_validity"] = {
        key: {"is_valid": valid} for key, valid in build_metric_validity(hierarchy).items()
    }
    _ = signals  # reserved for future calibrated signal overlay
    return payload


async def _tool_rolling_accuracy(
    db: AsyncSession,
    ticker: str,
    *,
    window: str = "all",
) -> dict[str, Any]:
    from app.services.market_data.series_loader import load_forecast_price_series
    from app.services.prediction_hierarchy.hierarchy_validation import HierarchyValidationEngine

    instrument = await _resolve_ticker(db, ticker)
    prices, volumes, _src = await load_forecast_price_series(
        db, instrument.id, instrument.symbol, persist=False
    )
    if len(prices) < 40:
        return {
            "ticker": instrument.symbol,
            "windows": [],
            "insufficient_data": True,
        }

    engine = HierarchyValidationEngine()
    report = engine.run(
        instrument_id=instrument.id,
        prices=prices,
        volumes=volumes,
    )
    windows = [m.to_dict() for m in report.rolling_window_metrics]
    if window != "all":
        try:
            target = int(window.replace("d", ""))
            windows = [w for w in windows if w.get("window_days") == target]
        except ValueError:
            pass
    return {
        "ticker": instrument.symbol,
        "windows": windows,
        "calibration_bins_count": len(report.calibration_error_series),
        "insufficient_data": not windows,
    }


async def _tool_correlation_matrix(
    db: AsyncSession,
    tickers: list[str],
) -> dict[str, Any]:
    from app.services.forecast.global_macro_view import get_global_macro_view_builder

    view = await get_global_macro_view_builder().build(db, symbols=tickers[:8])
    return {
        "tickers": list(tickers),
        "correlation_matrix": view.correlation_matrix,
        "correlation_symbols": list(view.correlation_symbols),
        "regime_map": [e.to_dict() for e in view.regime_map],
        "as_of": view.as_of,
    }


async def _tool_current_forecast(db: AsyncSession, ticker: str) -> dict[str, Any]:
    """Live forecast with the same suppression/honesty flags as the Forecast UI."""
    from app.services.qa.feature_flags import is_enabled
    from app.services.forecast_core.service import for_chat

    if is_enabled("qa_forecast_core"):
        return for_chat(ticker)
    from app.services.forecast.probability_map import build_metric_validity
    from app.services.prediction_hierarchy.orchestrator import get_hierarchy_orchestrator

    instrument = await _resolve_ticker(db, ticker)
    hierarchy = await get_hierarchy_orchestrator().get_forecast(
        db, instrument.id, symbol=instrument.symbol, include_narrative=False
    )
    point = hierarchy.point_forecast
    suppressed = False
    suppression_ru = None
    validity = {key: bool(valid) for key, valid in build_metric_validity(hierarchy).items()}
    if hierarchy.calibrated_confidence is not None and hierarchy.calibrated_confidence < 0.35:
        suppressed = True
        suppression_ru = (
            "Направление прогноза подавлено: калиброванная уверенность ниже порога честности."
        )
    payload: dict[str, Any] = {
        "ticker": instrument.symbol,
        "calibrated_confidence": hierarchy.calibrated_confidence,
        "expected_return_sign": getattr(point, "expected_return_sign", None) if point else None,
        "momentum_score": getattr(point, "momentum_score", None) if point else None,
        "metric_validity": validity,
        "direction_suppressed": suppressed,
        "suppression_message_ru": suppression_ru,
        "as_of": getattr(hierarchy, "as_of", None) or _utc_now(),
    }
    if suppressed:
        payload["insufficient_data"] = False
        payload["data_available"] = True
        payload["forecast_usable"] = False
    if not point:
        payload["insufficient_data"] = True
        payload["error"] = "no_forecast"
    try:
        from app.services.forecast_log.emit import emit_chat

        emit_chat(payload)
    except Exception:
        pass
    return payload


async def _tool_portfolio_risk(
    db: AsyncSession,
    *,
    owner_user_id: str | None,
    owner_email: str | None,
) -> dict[str, Any]:
    from app.services.qa.feature_flags import is_enabled
    from app.services.risk_engine.service import compute_risk_for_user

    if not owner_user_id:
        return {"error": "no_user_context", "insufficient_data": True, "data_status": "нет данных"}
    if not is_enabled("qa_risk_engine"):
        return {"error": "flag_off", "data_status": "флаг выключен"}
    payload = compute_risk_for_user(owner_user_id, "paper")
    if is_enabled("qa_report"):
        from app.services.portfolio_report.service import assemble

        payload["report"] = assemble(user_id=owner_user_id, mode="paper")
    if is_enabled("qa_act_desk"):
        from app.services.act_desk.service import journal_for

        payload["act_journal"] = journal_for(owner_user_id)[-5:]
    return payload


async def _tool_position_pnl(
    db: AsyncSession,
    *,
    ticker: str | None,
    owner_user_id: str | None,
    owner_email: str | None,
) -> dict[str, Any]:
    from app.services.portfolio.live_equity import compute_live_pnl
    from app.services.portfolio.positions_snapshot import build_open_positions_snapshot
    from app.services.portfolio.user_scope import get_user_by_email

    email = owner_email
    if not email and owner_user_id:
        from sqlalchemy import select

        from app.db.models import User

        row = (await db.execute(select(User.email).where(User.id == owner_user_id))).scalar_one_or_none()
        email = row
    if not email:
        return {"error": "no_user_context", "insufficient_data": True}

    user = await get_user_by_email(db, email)
    live = await compute_live_pnl(db, owner_user_id=user.id if user else None, owner_email=email)
    snapshot = await build_open_positions_snapshot(email, db, page_size=100)
    items = snapshot.get("items") or []
    positions = []
    for item in items:
        data = item.model_dump() if hasattr(item, "model_dump") else dict(item)
        sym = str(data.get("ticker") or "").upper()
        if ticker and sym != ticker.strip().upper():
            continue
        positions.append(
            {
                "ticker": sym,
                "unrealized_pnl": data.get("unrealized_pnl"),
                "approx_profit": data.get("approx_profit"),
                "current_price": data.get("current_price"),
                "position_size_usd": data.get("position_size_usd"),
                "status": data.get("status"),
            }
        )
    if ticker and not positions:
        return {
            "ticker": ticker.strip().upper(),
            "error": "position_not_found",
            "insufficient_data": True,
            "as_of": snapshot.get("live_snapshot", {}).get("last_refresh_at") if isinstance(snapshot.get("live_snapshot"), dict) else None,
        }
    return {
        "ticker": ticker.strip().upper() if ticker else None,
        "positions": positions,
        "unrealized_total_usd": live.unrealized_total_usd,
        "realized_closed_usd": live.realized_closed_usd,
        "as_of": (
            snapshot.get("live_snapshot", {}).get("last_refresh_at")
            if isinstance(snapshot.get("live_snapshot"), dict)
            else _utc_now()
        ),
    }


async def _tool_search_instruments(db: AsyncSession, query: str) -> dict[str, Any]:
    from sqlalchemy import select

    from app.domain.instrument import InstrumentORM

    q = (query or "").strip().upper()
    if len(q) < 1:
        return {"error": "empty_query", "insufficient_data": True, "matches": []}
    stmt = (
        select(InstrumentORM.symbol, InstrumentORM.category, InstrumentORM.source, InstrumentORM.instrument_type)
        .where(InstrumentORM.symbol.ilike(f"{q}%"))
        .order_by(InstrumentORM.symbol.asc())
        .limit(20)
    )
    rows = (await db.execute(stmt)).all()
    matches = [
        {
            "symbol": r[0],
            "category": r[1],
            "source": r[2],
            "instrument_type": r[3],
        }
        for r in rows
    ]
    return {
        "query": q,
        "matches": matches,
        "count": len(matches),
        "insufficient_data": len(matches) == 0,
        "as_of": _utc_now(),
    }

