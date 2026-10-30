"""
Pipeline Celery task.
Orchestrates: data fetch → features → news → ML → risk → maneuvers → DB save.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from time import monotonic
from typing import Any

from celery import Task

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import Maneuver, ManeuverReport, ManeuverStatus, StrategyType, TradingMode
from app.tasks.async_runner import run_async
from app.tasks.celery_app import celery_app

# NOTE: numpy/pandas/scikit-learn/lightgbm are imported lazily inside the task
# body (via app.services.ml.* and app.services.risk.maneuver_generator), NOT at
# module import time. Celery imports every module listed in celery_app.include
# when the worker boots; a top-level heavy import here would crash the ENTIRE
# worker (blocking news ingestion and execution too) whenever those deps are
# missing — e.g. on a Python build without numpy wheels. Keeping them lazy lets
# the worker start and only the pipeline task fails, with a clear message.

logger = get_logger(__name__)


class PipelineDependencyError(RuntimeError):
    """Raised when heavy ML/data dependencies are unavailable at task runtime."""


@celery_app.task(
    bind=True,
    name="app.tasks.pipeline.run_pipeline_task",
    max_retries=2,
    default_retry_delay=30,
    track_started=True,
)
def run_pipeline_task(
    self: Task,
    run_id: str,
    watchlist: list[str],
    portfolio_size: float,
    confidence_threshold: float | None = None,
    triggered_by: str = "manual",
    skip_auto_execute: bool = False,
    owner_user_id: str | None = None,
) -> dict[str, Any]:
    """
    Full intelligence pipeline:
    1. Fetch market data for watchlist
    2. Fetch & score news
    3. Run ML predictions
    4. Run risk engine
    5. Generate 10 maneuvers
    6. Store in DB
    """
    from app.utils.pipeline_tracker import mark_complete, mark_failed

    redelivered = bool((getattr(self.request, "delivery_info", None) or {}).get("redelivered"))
    if redelivered and str(triggered_by).startswith("ops:"):
        # The worker restarted mid-run (deploy). The user has long stopped waiting for this run;
        # re-running it would only block their next click.
        logger.warning("Pipeline redelivered after restart, dropped", run_id=run_id)
        mark_failed(run_id, "Анализ прерван перезапуском сервера. Запустите его заново.")
        return {"run_id": run_id, "status": "dropped_redelivered"}

    logger.info("Pipeline started", run_id=run_id, tickers=watchlist, triggered_by=triggered_by)
    from app.utils.ws_notify import notify_pipeline_sync

    notify_pipeline_sync("pipeline_started", {"run_id": run_id, "triggered_by": triggered_by})

    try:
        result = run_async(
            _async_pipeline(
                run_id,
                watchlist,
                portfolio_size,
                confidence_threshold,
                triggered_by,
                skip_auto_execute=skip_auto_execute,
                owner_user_id=owner_user_id,
            )
        )
        report_id = result.get("report_id")
        if report_id:
            mark_complete(run_id, report_id)
        notify_pipeline_sync("pipeline_complete", {**result, "triggered_by": triggered_by})
        return result
    except PipelineDependencyError as exc:
        # Missing ML deps are a deployment issue, not a transient fault — do not
        # retry (that would just burn the retry budget). Report a clear failure.
        logger.error("Pipeline dependency missing", run_id=run_id, error=str(exc))
        mark_failed(run_id, str(exc))
        notify_pipeline_sync("pipeline_failed", {"run_id": run_id, "error": str(exc), "triggered_by": triggered_by})
        return {"run_id": run_id, "status": "failed", "error": str(exc)}
    except Exception as exc:
        logger.error("Pipeline failed", run_id=run_id, error=str(exc), exc_info=True)
        notify_pipeline_sync("pipeline_failed", {"run_id": run_id, "error": str(exc), "triggered_by": triggered_by})
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            mark_failed(run_id, str(exc))
            return {"run_id": run_id, "status": "failed", "error": str(exc)}


@celery_app.task(
    name="app.tasks.pipeline.run_scheduled_pipeline_task",
    track_started=True,
)
def run_scheduled_pipeline_task() -> dict[str, Any]:
    """
    Daily scheduled market-intelligence pipeline (celery-beat).

    Dispatches one pipeline run per eligible post-trial user so each user gets
    their own maneuver_reports.created_by. Maneuvers stay PENDING
    (skip_auto_execute=True) — same UX as manual /pipeline/run.
    """
    return run_async(_async_scheduled_pipeline())


async def _async_scheduled_pipeline() -> dict[str, Any]:
    from app.db.session import AsyncSessionLocal
    from app.services.pipeline.eligible_users import list_pipeline_eligible_users
    from app.services.portfolio.metrics import _user_confidence_threshold, _user_effective_deploy_cap
    from app.services.settings.watchlist import get_effective_watchlist
    from app.utils.pipeline_tracker import track_run

    dispatched: list[dict[str, Any]] = []

    async with AsyncSessionLocal() as session:
        users = await list_pipeline_eligible_users(session)

    if not users:
        logger.info("Scheduled pipeline: no eligible users")
        return {"status": "skipped", "reason": "no_eligible_users", "runs": []}

    for user in users:
        run_id = str(uuid.uuid4())
        async with AsyncSessionLocal() as session:
            watchlist = await get_effective_watchlist(session, user.email)
            portfolio_size = await _user_effective_deploy_cap(user.email, session)
            confidence_threshold = await _user_confidence_threshold(user.email)

        logger.info(
            "Scheduled pipeline dispatch for user",
            run_id=run_id,
            user_id=user.id,
            email=user.email,
            tickers=watchlist,
            portfolio_size=portfolio_size,
        )

        from app.utils.pipeline_dispatch import dispatch_pipeline_task

        task_id = dispatch_pipeline_task(
            run_id=run_id,
            watchlist=watchlist,
            portfolio_size=portfolio_size,
            confidence_threshold=confidence_threshold,
            triggered_by=f"beat:{user.email}",
            skip_auto_execute=True,
            owner_user_id=user.id,
        )
        track_run(run_id, task_id, triggered_by=f"beat:{user.email}")
        dispatched.append(
            {
                "run_id": run_id,
                "task_id": task_id,
                "user_id": user.id,
                "email": user.email,
                "watchlist": watchlist,
            }
        )

    return {
        "status": "queued",
        "user_count": len(dispatched),
        "skip_auto_execute": True,
        "runs": dispatched,
    }


async def _resolve_report_owner_id(session, triggered_by: str) -> str | None:
    """Resolve maneuver report owner from trigger context.

    User-visible runs must resolve to the triggering user (email in triggered_by
    or explicit owner_user_id passed to the task). PIPELINE_OWNER_EMAIL and admin
    fallback apply only to system: ops triggers — never shown in user dashboards.
    """
    from sqlalchemy import select

    from app.db.models import User, UserRole

    owner_email: str | None = None
    owner_user_id: str | None = None
    is_system_ops = triggered_by.strip().lower().startswith("system:")

    if triggered_by:
        candidate = triggered_by.split(":", 1)[-1].strip().lower()
        if candidate.startswith("user:"):
            owner_user_id = candidate.removeprefix("user:").strip()
        elif "@" in candidate:
            owner_email = candidate

    if owner_user_id:
        user_row = await session.execute(select(User).where(User.id == owner_user_id))
        owner = user_row.scalar_one_or_none()
        if owner:
            return owner.id

    if owner_email:
        user_row = await session.execute(select(User).where(User.email == owner_email))
        owner = user_row.scalar_one_or_none()
        if owner:
            return owner.id

    if not is_system_ops:
        return None

    if settings.PIPELINE_OWNER_EMAIL.strip():
        owner_email = settings.PIPELINE_OWNER_EMAIL.strip().lower()
        user_row = await session.execute(select(User).where(User.email == owner_email))
        owner = user_row.scalar_one_or_none()
        if owner:
            return owner.id

    admin_row = await session.execute(
        select(User)
        .where(User.role == UserRole.ADMIN, User.is_active.is_(True))
        .order_by(User.created_at)
        .limit(1)
    )
    admin = admin_row.scalar_one_or_none()
    return admin.id if admin else None


async def _async_pipeline(
    run_id: str,
    watchlist: list[str],
    portfolio_size: float,
    confidence_threshold: float | None,
    triggered_by: str,
    *,
    skip_auto_execute: bool = False,
    owner_user_id: str | None = None,
) -> dict[str, Any]:
    try:
        import pandas as pd  # noqa: F401

        from app.services.pipeline.market_regime import compute_market_regime, regime_to_macro_score
        from app.services.risk.maneuver_generator import ManeuverGenerator, ManeuverOutput
    except ImportError as exc:
        raise PipelineDependencyError(
            "Pipeline ML/data dependencies are not installed "
            "(numpy / pandas / scikit-learn / lightgbm). Install "
            "backend/requirements-pipeline.txt into a Python 3.11 venv and run "
            f"the Celery worker from that venv. Original import error: {exc}"
        ) from exc

    from app.db.session import AsyncSessionLocal
    from app.services.control_fabric.strategy_halt import check_strategy_halt_async
    halt = await check_strategy_halt_async()
    if halt.halted:
        logger.warning("Pipeline skipped — kill switch active", reason=halt.reason)
        return {
            "run_id": run_id,
            "status": "halted",
            "reason": halt.reason,
            "halt_source": halt.source,
        }

    from app.services.market_data.nightly_digest import load_latest_digest
    from app.services.pipeline.tradeable_universe import resolve_analysis_universe

    digest = load_latest_digest()
    pins = list(watchlist)
    async with AsyncSessionLocal() as uni_session:
        oid = owner_user_id or await _resolve_report_owner_id(uni_session, triggered_by)
        universe = await resolve_analysis_universe(
            uni_session,
            owner_user_id=oid,
            pins=pins,
            digest=digest,
        )
    watchlist = universe.tickers
    max_tickers = int(settings.PIPELINE_MAX_TICKERS)
    if max_tickers > 0 and len(watchlist) > max_tickers:
        logger.info(
            "Pipeline watchlist capped",
            requested=len(watchlist),
            capped=max_tickers,
        )
        watchlist = watchlist[:max_tickers]

    end = datetime.now(timezone.utc)
    lookback_days = max(30, int(settings.PIPELINE_BAR_LOOKBACK_DAYS))
    start = end - timedelta(days=lookback_days)
    bar_limit = max(130, lookback_days + 30)

    from app.db.session import AsyncSessionLocal
    from app.services.news.client import fetch_news_sentiment
    from app.services.macro.client import get_macro_score, maybe_refresh_macro_events
    from app.services.pipeline.io import fetch_watchlist_bars_parallel
    from app.services.portfolio.exposure import maneuver_exposure

    async def _load_macro() -> tuple[float, list[dict]]:
        async with AsyncSessionLocal() as macro_session:
            try:
                await maybe_refresh_macro_events(macro_session)
                return await get_macro_score(macro_session, live_calendar=False)
            except Exception as exc:
                logger.warning("Macro event fetch failed, using regime proxy", error=str(exc))
                return 0.0, []

    async def _load_exposure() -> tuple[float, int]:
        async with AsyncSessionLocal() as exposure_session:
            try:
                oid = owner_user_id or await _resolve_report_owner_id(exposure_session, triggered_by)
                return await maneuver_exposure(exposure_session, owner_user_id=oid)
            except Exception as exc:
                logger.warning("Could not load live portfolio exposure", error=str(exc))
                return 0.0, 0

    async def _bounded(coro: Any, seconds: float, fallback: Any, stage: str) -> Any:
        """A stage that overruns its budget yields its fallback; the analysis still finishes."""
        try:
            return await asyncio.wait_for(coro, timeout=seconds)
        except asyncio.TimeoutError:
            logger.warning("Pipeline stage over budget, using fallback", run_id=run_id, stage=stage, budget_sec=seconds)
            return fallback

    t_parallel = monotonic()
    (
        bars_result,
        news_sentiment,
        macro_result,
        exposure_result,
    ) = await asyncio.gather(
        fetch_watchlist_bars_parallel(watchlist, start, end, bar_limit=bar_limit),
        _bounded(fetch_news_sentiment(watchlist), 60, {}, "news"),
        _bounded(_load_macro(), 45, (0.0, []), "macro"),
        _bounded(_load_exposure(), 20, (0.0, 0), "exposure"),
    )
    market_data, raw_bars_by_ticker = bars_result
    macro_score, macro_events = macro_result
    live_exposure_usd, live_open_count = exposure_result
    logger.info(
        "Pipeline parallel prep complete",
        run_id=run_id,
        tickers=len(market_data),
        news=len(news_sentiment),
        macro_events=len(macro_events),
        elapsed_sec=round(monotonic() - t_parallel, 2),
    )

    if not market_data:
        raise RuntimeError("No market data fetched for any ticker in watchlist")

    market_regime = compute_market_regime(market_data)
    regime = str(market_regime.get("regime") or "unknown")
    digest_macro = None
    if digest:
        try:
            digest_macro = float(digest.get("macro_score"))
        except (TypeError, ValueError):
            digest_macro = None
    if not macro_events:
        macro_score = regime_to_macro_score(
            regime,
            breadth=float(market_regime.get("breadth") or 0.0),
            digest_macro=digest_macro,
        )
    elif digest_macro is not None:
        macro_score = 0.8 * float(macro_score) + 0.2 * digest_macro
    try:
        from app.services.quant_desk.alt_macro import load_local_alt_macro

        alt_tilt = float((load_local_alt_macro() or {}).get("tilt") or 0.0)
        macro_score = max(-1.0, min(1.0, 0.85 * float(macro_score) + 0.15 * alt_tilt))
    except Exception:
        raise

    # ── Step 4: Generate maneuvers ─────────────────────────────────────────────
    # Derive per-ticker event effect from macro/Investing.com events so
    # earnings + economic catalysts feed the news/events scoring component.
    events_by_ticker = _events_by_ticker(macro_events, watchlist)

    from app.services.risk.engine import PortfolioState

    from app.core.config import settings as app_settings
    from app.services.risk.portfolio_sizing import resolve_portfolio_size_usd

    effective_threshold = (
        confidence_threshold
        if confidence_threshold is not None
        else app_settings.NO_TRADE_CONFIDENCE_THRESHOLD
    )
    # portfolio_size from dispatch is already effective cap; never replace a positive
    # operator cap with the $10k unset fallback.
    sizing_portfolio = (
        float(portfolio_size)
        if portfolio_size is not None and float(portfolio_size) > 0
        else resolve_portfolio_size_usd(portfolio_size)
    )
    logger.info(
        "Pipeline sizing cap",
        run_id=run_id,
        dispatched_portfolio_size=portfolio_size,
        sizing_portfolio=sizing_portfolio,
    )

    generator = ManeuverGenerator(
        portfolio_size=sizing_portfolio,
        confidence_threshold=effective_threshold,
    )
    interval_forecasts: dict = {}
    hierarchy_hints: dict = {}
    try:
        from app.services.risk.hierarchy_intervals import (
            load_intervals_and_hints_for_tickers,
            warm_missing_hierarchy_hints,
        )

        t_intervals = monotonic()
        async with AsyncSessionLocal() as interval_session:
            interval_forecasts, hierarchy_hints = await load_intervals_and_hints_for_tickers(
                interval_session,
                list(market_data.keys()),
                use_orchestrator=False,
            )
            hierarchy_hints, interval_forecasts = await _bounded(
                warm_missing_hierarchy_hints(
                    interval_session,
                    list(market_data.keys()),
                    hierarchy_hints,
                    interval_forecasts,
                    max_warm=8,
                ),
                60,
                (hierarchy_hints, interval_forecasts),
                "hierarchy_warm",
            )
        logger.info(
            "Pipeline intervals loaded",
            run_id=run_id,
            tickers=len(interval_forecasts),
            hints=sum(1 for h in hierarchy_hints.values() if getattr(h, "cache_hit", False)),
            elapsed_sec=round(monotonic() - t_intervals, 2),
        )
    except Exception as exc:
        logger.warning("Hierarchy intervals skipped for pipeline", error=str(exc))

    debate_result = None
    book_quotes: dict = {}
    try:
        from app.services.risk.maneuver_debate import (
            debate_enabled,
            run_maneuver_debate,
            structural_debate,
        )

        from app.services.news.client import last_news_article_counts

        pre_candidates = generator.build_candidates(
            market_data,
            news_sentiment=news_sentiment,
            macro_score=macro_score,
            events_by_ticker=events_by_ticker,
            hierarchy_hints=hierarchy_hints,
            news_article_counts=last_news_article_counts(),
        )
        debate_result = structural_debate(pre_candidates)
        if app_settings.PIPELINE_LLM_DEBATE_ENABLED and debate_enabled():
            llm_debate = await run_maneuver_debate(pre_candidates)
            if llm_debate and llm_debate.get("ok"):
                debate_result = llm_debate
        try:
            from app.services.quant_desk.book_quotes import prefetch_book_quotes

            ranked = sorted(
                pre_candidates,
                key=lambda c: getattr(c, "composite_score", 0.0),
                reverse=True,
            )
            book_quotes = await _bounded(
                prefetch_book_quotes([getattr(c, "ticker", "") for c in ranked], limit=15),
                30,
                {},
                "book_quotes",
            )
        except Exception as exc:
            logger.warning("Book quote prefetch skipped", error=str(exc))
    except Exception as exc:
        logger.warning("Maneuver debate skipped", error=str(exc))

    if not book_quotes:
        try:
            from app.services.quant_desk.book_quotes import prefetch_book_quotes

            book_quotes = await _bounded(prefetch_book_quotes(list(market_data.keys()), limit=15), 30, {}, "book_quotes")
        except Exception as exc:
            logger.warning("Book quote prefetch fallback skipped", error=str(exc))

    book_state = PortfolioState()
    owner_email = None
    async with AsyncSessionLocal() as book_session:
        from app.db.models import User
        from app.db.rls import set_session_user_id
        from app.services.portfolio.exposure import current_exposure

        owner_id = owner_user_id or await _resolve_report_owner_id(book_session, triggered_by)
        owner_email = None
        if owner_id:
            await set_session_user_id(book_session, owner_id)
            owner = await book_session.get(User, owner_id)
            owner_email = owner.email if owner else None
        snap = await current_exposure(
            book_session,
            owner_user_id=owner_id,
            owner_email=owner_email,
        )
        book_state = PortfolioState(
            total_exposure_usd=float(snap.total_usd),
            open_positions=int(snap.open_maneuvers),
        )

    t_generate = monotonic()
    reserved: set[str] = set()
    bot_risk_snapshot = None
    try:
        from app.services.bot_risk.guard import build_snapshot_from_stores
        from app.services.portfolio.capital_overlap import (
            grid_occupied_tickers,
            maneuver_occupied_tickers_for_email,
        )
        from app.utils.cache import cache_get

        bots = await cache_get("grid:bots") or {}
        dca_bots = await cache_get("dca:bots") or {}
        mom_bots = await cache_get("momentum:bots") or {}
        reserved = grid_occupied_tickers(bots if isinstance(bots, dict) else {}, owner_email)
        async with AsyncSessionLocal() as occ_session:
            reserved |= await maneuver_occupied_tickers_for_email(occ_session, owner_email)
        bot_risk_snapshot = build_snapshot_from_stores(
            grid=bots if isinstance(bots, dict) else {},
            dca=dca_bots if isinstance(dca_bots, dict) else {},
            momentum=mom_bots if isinstance(mom_bots, dict) else {},
        )
    except Exception:
        reserved = reserved or set()
    from app.services.news.client import last_news_article_counts

    maneuver_outputs: list[ManeuverOutput] = generator.generate(
        market_data=market_data,
        news_sentiment=news_sentiment,
        macro_score=macro_score,
        events_by_ticker=events_by_ticker,
        portfolio_state=book_state,
        interval_forecasts=interval_forecasts,
        debate_result=debate_result,
        reserved_tickers=reserved,
        hierarchy_hints=hierarchy_hints,
        news_article_counts=last_news_article_counts(),
        user_id=str(owner_id or "paper"),
        book_quotes=book_quotes,
        bot_risk_snapshot=bot_risk_snapshot,
        market_regime=market_regime,
    )
    logger.info(
        "Pipeline maneuvers generated",
        run_id=run_id,
        count=len(maneuver_outputs),
        elapsed_sec=round(monotonic() - t_generate, 2),
    )

    # Persist daily bars after analysis so a slow DB write cannot block maneuver generation.
    try:
        from app.db.session import AsyncSessionLocal as _BarSession
        from app.services.market_data.bars import _persist_bars

        async with _BarSession() as bar_session:
            for ticker, bars in raw_bars_by_ticker.items():
                try:
                    await _persist_bars(bar_session, ticker, "1d", bars)
                except Exception as exc:
                    logger.warning("Bar persist failed", ticker=ticker, error=str(exc))
    except Exception as exc:
        logger.warning("Bar persistence step skipped", error=str(exc))

    # ── Step 5: Save to DB ─────────────────────────────────────────────────────
    async with AsyncSessionLocal() as session:
        created_by_user_id = owner_user_id or await _resolve_report_owner_id(
            session, triggered_by
        )
        if not created_by_user_id:
            raise RuntimeError(
                "Pipeline report owner could not be resolved; "
                "cannot persist under row-level security"
            )

        trading_mode = TradingMode.PAPER
        from app.services.trading_keys.user_executor import resolve_user_account_mode

        if await resolve_user_account_mode(session, created_by_user_id) == "live":
            trading_mode = TradingMode.LIVE

        from app.db.rls import set_session_user_id

        await set_session_user_id(session, created_by_user_id)

        report = ManeuverReport(
            pipeline_run_id=run_id,
            watchlist=watchlist,
            created_by=created_by_user_id,
            regime=regime,
            market_context={
                "macro_score": macro_score,
                "macro_events_count": len(macro_events),
                "tickers_analyzed": len(market_data),
                "tickers_requested": len(watchlist),
                "tradeable_count": 0,
                "above_threshold_count": (
                    generator.last_confidence_filter.above_threshold_count
                    if generator.last_confidence_filter
                    else sum(1 for m in maneuver_outputs if not m.is_no_trade)
                ),
                "backfill_count": (
                    generator.last_confidence_filter.backfill_count
                    if generator.last_confidence_filter
                    else 0
                ),
                "live_exposure_usd": live_exposure_usd or book_state.total_exposure_usd,
                "live_open_positions": live_open_count or book_state.open_positions,
                "reserved_tickers": sorted(reserved),
                "hierarchy_cache_hits": sum(
                    1 for h in hierarchy_hints.values() if getattr(h, "cache_hit", False)
                ),
                "nightly_digest_as_of": (digest or {}).get("as_of") if digest else None,
                "analysis_universe": watchlist,
                "analysis_pins": pins,
                "analysis_venues": universe.venues,
                "market_regime_detail": market_regime,
                "book_quotes_tickers": sorted(book_quotes.keys()),
                "debate_pattern": (debate_result or {}).get("pattern"),
                "maneuver_slots": settings.MANEUVER_COUNT,
                "portfolio_size_usd": portfolio_size,
                "sizing_portfolio_usd": sizing_portfolio,
                "confidence_threshold": effective_threshold,
                "confidence_filter": (
                    generator.last_confidence_filter.to_dict()
                    if generator.last_confidence_filter
                    else None
                ),
                "triggered_by": triggered_by,
            },
            status="complete",
        )
        session.add(report)
        await session.flush()

        db_maneuvers: list[Maneuver] = []
        from app.utils.json_safe import coerce_finite_float, finite_float
        from app.services.risk.maneuver_dedupe import (
            existing_maneuver_keys,
            maneuver_content_key,
            supersede_pending_duplicates,
        )

        def _opt(v: float | None) -> float | None:
            return finite_float(v)

        seen_keys = await existing_maneuver_keys(session, user_id=created_by_user_id)
        from app.services.risk.portfolio_sizing import enforce_hard_deploy_caps

        enforce_hard_deploy_caps(maneuver_outputs, sizing_portfolio)
        withdrawn = await supersede_pending_duplicates(
            session,
            user_id=created_by_user_id,
            new_keys={
                maneuver_content_key(o.ticker, o.direction, o.confidence, o.rationale)
                for o in maneuver_outputs
            }
            - seen_keys,
        )
        if withdrawn:
            logger.info("Older pending copies withdrawn", count=withdrawn, run_id=run_id)
        for out in maneuver_outputs:
            key = maneuver_content_key(out.ticker, out.direction, out.confidence, out.rationale)
            if key in seen_keys:
                logger.info("Skip duplicate maneuver", ticker=out.ticker, user_id=created_by_user_id)
                continue
            seen_keys.add(key)
            strategy = _map_strategy(out.strategy_type)
            maneuver = Maneuver(
                report_id=report.id,
                rank=out.rank,
                ticker=out.ticker,
                strategy_type=strategy,
                direction=out.direction,
                entry_zone_low=_opt(out.entry_zone_low),
                entry_zone_high=_opt(out.entry_zone_high),
                exit_zone_low=_opt(out.exit_zone_low),
                exit_zone_high=_opt(out.exit_zone_high),
                stop_loss=_opt(out.stop_loss),
                take_profit=_opt(out.take_profit),
                invalidation_level=_opt(out.invalidation_level),
                risk_percent=coerce_finite_float(out.risk_percent, 0.0),
                position_size_usd=coerce_finite_float(out.position_size_usd, 0.0),
                expected_return_low=_opt(out.expected_return_low),
                expected_return_high=_opt(out.expected_return_high),
                expected_pnl_low=_opt(out.expected_pnl_low),
                expected_pnl_high=_opt(out.expected_pnl_high),
                confidence=coerce_finite_float(out.confidence, 0.0),
                time_horizon=out.time_horizon,
                catalyst=out.catalyst,
                rationale=out.rationale,
                execution_plan=out.execution_plan,
                source_signals=out.source_signals,
                signal_meta=out.signal_meta or {},
                status=ManeuverStatus.PENDING,
                trading_mode=trading_mode,
            )
            session.add(maneuver)
            db_maneuvers.append(maneuver)

        from app.services.pipeline.maneuver_counts import count_tradeable_persisted

        tradeable_persisted = count_tradeable_persisted(db_maneuvers)
        if isinstance(report.market_context, dict):
            report.market_context = {
                **report.market_context,
                "tradeable_count": tradeable_persisted,
            }

        # Build text summary
        from app.schemas.schemas import ManeuverOut, ManeuverReportOut
        report.text_summary = _build_text_summary(maneuver_outputs, regime)

        await session.commit()
        report_id = report.id
        maneuver_ids = [str(m.id) for m in db_maneuvers]

    # ── Step 6: Paper auto-execute (approve → fill without manual step) ────────
    auto_exec_result: dict[str, Any] = {}
    if not skip_auto_execute:
        try:
            from app.services.execution.auto_execute import auto_execute_paper_maneuvers

            auto_exec_result = await auto_execute_paper_maneuvers(maneuver_ids)
            if auto_exec_result.get("filled"):
                logger.info(
                    "Paper auto-execute complete",
                    run_id=run_id,
                    filled=auto_exec_result.get("filled"),
                    rejected=auto_exec_result.get("rejected"),
                )
        except Exception as exc:
            logger.warning("Paper auto-execute step failed", run_id=run_id, error=str(exc))
    else:
        auto_exec_result = {"enabled": False, "skipped": len(maneuver_ids), "reason": "manual_run"}
        logger.info(
            "Pipeline left maneuvers pending for operator approval",
            run_id=run_id,
            maneuver_count=len(maneuver_ids),
        )

    logger.info("Pipeline complete", run_id=run_id, report_id=report_id, maneuvers=len(maneuver_outputs))
    return {
        "run_id": run_id,
        "report_id": report_id,
        "maneuver_count": len(maneuver_outputs),
        "paper_auto_execute": auto_exec_result,
    }


def _events_by_ticker(
    macro_events: list[dict], watchlist: list[str]
) -> dict[str, float]:
    """Aggregate macro/Investing.com event effects into a per-ticker score (-1..1).

    Averages the ``market_effect`` of every event whose ``tickers_affected``
    includes the ticker, weighted by event confidence. Tickers with no matching
    event get 0.0 (neutral). Crypto tickers usually have no event coverage
    (no dedicated crypto sentiment API), so they fall through to news/technical.
    """
    watch = {t.upper() for t in watchlist}
    sums: dict[str, float] = {}
    weights: dict[str, float] = {}
    for ev in macro_events or []:
        try:
            effect = float(ev.get("market_effect", 0.0))
            conf = float(ev.get("confidence", 0.5))
        except (TypeError, ValueError):
            continue
        for raw in ev.get("tickers_affected", []) or []:
            ticker = str(raw).upper()
            if ticker not in watch:
                continue
            sums[ticker] = sums.get(ticker, 0.0) + effect * conf
            weights[ticker] = weights.get(ticker, 0.0) + conf
    result: dict[str, float] = {}
    for ticker, weight in weights.items():
        if weight > 0:
            result[ticker] = max(-1.0, min(1.0, sums[ticker] / weight))
    return result


def _regime_to_macro_score(regime: str) -> float:
    from app.services.pipeline.market_regime import regime_to_macro_score

    return regime_to_macro_score(regime)


def _map_strategy(s: str) -> StrategyType:
    mapping = {
        "momentum": StrategyType.MOMENTUM,
        "mean_reversion": StrategyType.MEAN_REVERSION,
        "breakout": StrategyType.BREAKOUT,
        "grid": StrategyType.GRID,
        "event_driven": StrategyType.EVENT_DRIVEN,
        "trend_following": StrategyType.TREND_FOLLOWING,
        "macro": StrategyType.MACRO,
        "no_trade": StrategyType.NO_TRADE,
    }
    return mapping.get(s, StrategyType.MOMENTUM)


def _build_text_summary(maneuvers: list[ManeuverOutput], regime: str) -> str:
    tradeable = [m for m in maneuvers if not m.is_no_trade]
    lines = [
        f"Предоставлено {settings.MANEUVER_COUNT} инвестиционных маневров.",
        f"Режим рынка: {regime}. Торгуемых: {len(tradeable)}/{settings.MANEUVER_COUNT}.",
        "",
    ]
    for m in maneuvers:
        if m.is_no_trade:
            lines.append(f"{m.rank} — НЕТ СДЕЛКИ ({m.ticker}): {m.rationale}")
        else:
            ret_str = (
                f"{m.expected_return_low:.1f}%–{m.expected_return_high:.1f}%"
                if m.expected_return_low is not None else "N/A"
            )
            pnl_str = (
                f"${m.expected_pnl_low:,.0f}–${m.expected_pnl_high:,.0f}"
                if m.expected_pnl_low is not None else "N/A"
            )
            lines.append(
                f"{m.rank} — {m.ticker} ({m.direction}): "
                f"вложить ${m.position_size_usd:,.0f}, "
                f"ожидаемый доход {ret_str} ({pnl_str}), "
                f"срок {m.time_horizon}, "
                f"риск {m.risk_percent:.1f}%, "
                f"уверенность {m.confidence:.0%}."
            )
    return "\n".join(lines)
