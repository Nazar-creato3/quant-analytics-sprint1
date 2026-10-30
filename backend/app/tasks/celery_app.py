from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings
from app.services.ops_observe.otel import setup as setup_otel

setup_otel()

from app.core.http_proxy import configure_yfinance_proxy  # noqa: E402

configure_yfinance_proxy()

celery_app = Celery(
    "apex_intel",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.tasks.data_ingestion",
        "app.tasks.pipeline",
        "app.tasks.execution",
        "app.tasks.backtest",
        "app.tasks.backtest_analysis",
        "app.tasks.event_risk",
        "app.tasks.liquidity",
        "app.tasks.stress_harness",
        "app.tasks.grid",
        "app.tasks.strategy_bots",
        "app.tasks.forecast",
        "app.tasks.forecast_log",
        "app.tasks.macro_registry",
        "app.tasks.price_history",
        "app.tasks.access_policy",
        "app.tasks.alerts",
        "app.tasks.orders",
        "app.tasks.position_audit",
        "app.tasks.fleet_audit",
        "app.tasks.robot",
        "app.tasks.stooq_bulk",
        "app.tasks.fred_bulk",
        "app.tasks.equity_eod",
        "app.tasks.crm_sync",
        "app.tasks.email",
        "app.tasks.health_reporter",
        "app.tasks.bonds",
        "app.tasks.factor_lens",
        "app.tasks.futures_market",
    ],
)

celery_app.conf.update(
    task_track_started=True,
    worker_send_task_events=True,
    task_send_sent_event=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    broker_connection_retry_on_startup=True,
    timezone="UTC",
    enable_utc=True,
    task_routes={
        "app.tasks.data_ingestion.*": {"queue": "ingestion"},
        "app.tasks.stooq_bulk.*": {"queue": "ingestion"},
        "app.tasks.fred_bulk.*": {"queue": "ingestion"},
        "app.tasks.equity_eod.*": {"queue": "ingestion"},
        "app.tasks.pipeline.*": {"queue": "pipeline"},
        "app.tasks.execution.*": {"queue": "execution"},
        "app.tasks.backtest.*": {"queue": "backtest"},
        "app.tasks.backtest_analysis.*": {"queue": "backtest"},
        # Periodic ticks/monitors — default celery queue so manual pipeline runs are not starved.
        "app.tasks.grid.*": {"queue": "celery"},
        "app.tasks.strategy_bots.*": {"queue": "celery"},
        "app.tasks.event_risk.*": {"queue": "celery"},
        "app.tasks.liquidity.*": {"queue": "celery"},
        "app.tasks.forecast.*": {"queue": "celery"},
        "app.tasks.forecast_log.*": {"queue": "celery"},
        "app.tasks.position_audit.*": {"queue": "celery"},
        "app.tasks.fleet_audit.*": {"queue": "celery"},
        "app.tasks.robot.*": {"queue": "celery"},
        "app.tasks.email.*": {"queue": "celery"},
    },
    task_default_queue="celery",
    broker_transport_options={
        "priority_steps": list(range(10)),
        "sep": ":",
        "queue_order_strategy": "priority",
    },
    beat_schedule={
        "refresh-tbank-orders": {
            "task": "app.tasks.execution.refresh_tbank_orders_task",
            "schedule": 60.0,
            "options": {"queue": "execution", "expires": 55},
        },
        "pdn-retention-daily": {
            "task": "app.tasks.pdn_retention.run_pdn_retention",
            "schedule": crontab(minute=20, hour=4),
        },
        "rebuild-factor-returns-daily": {
            "task": "app.tasks.factor_lens.rebuild_factor_returns",
            "schedule": crontab(minute=10, hour=5),
            "options": {"queue": "ingestion"},
        },
        "rebuild-futures-market-daily": {
            "task": "app.tasks.futures_market.rebuild_futures_market",
            "schedule": crontab(minute=40, hour=5),
            "options": {"queue": "ingestion"},
        },
        "ingest-market-data-hourly": {
            "task": "app.tasks.data_ingestion.ingest_market_data_task",
            "schedule": crontab(minute=15, hour="*"),
            "options": {"queue": "ingestion"},
        },
        "ingest-news-every-15min": {
            "task": "app.tasks.data_ingestion.ingest_news_task",
            "schedule": crontab(minute="*/15"),
            "options": {"queue": "ingestion"},
        },
        "ingest-investing-intel-every-30min": {
            "task": "app.tasks.data_ingestion.ingest_investing_intel_task",
            "schedule": crontab(minute="5,35"),
            "options": {"queue": "ingestion"},
        },
        "refresh-bonds-daily": {
            "task": "app.tasks.bonds.refresh_bond_reference_task",
            "schedule": crontab(minute=10, hour=7),
            "options": {"queue": "ingestion"},
        },
        "ingest-macro-daily": {
            "task": "app.tasks.data_ingestion.ingest_macro_events_task",
            "schedule": crontab(minute=0, hour=8),
            "options": {"queue": "ingestion"},
        },
        "ingest-macro-indicators-daily": {
            "task": "app.tasks.data_ingestion.ingest_macro_indicators_task",
            "schedule": crontab(minute=30, hour=8),
            "options": {"queue": "ingestion"},
        },
        # ALWAYS ON: Stooq daily ASCII bulk (ZIP). Soft-keeps previous on bandwidth/auth fail.
        "sync-stooq-bulk-nightly": {
            "task": "app.tasks.stooq_bulk.sync_stooq_bulk_task",
            "schedule": crontab(minute=40, hour=2),
            "options": {"queue": "ingestion"},
        },
        # FRED + pandas_datareader macro/factors (WB, Fama-French) — not equity OHLCV.
        "sync-fred-bulk-nightly": {
            "task": "app.tasks.fred_bulk.sync_fred_bulk_task",
            "schedule": crontab(minute=50, hour=2),
            "options": {"queue": "ingestion"},
        },
        # Board/liquid equity EOD via Tiingo+Yahoo — Stooq complement for /markets.
        "sync-equity-eod-nightly": {
            "task": "app.tasks.equity_eod.sync_equity_eod_task",
            "schedule": crontab(minute=55, hour=2),
            "options": {"queue": "ingestion"},
        },
        "refresh-admin-fleet-audit-nightly": {
            "task": "app.tasks.fleet_audit.refresh_fleet_audit_task",
            "schedule": crontab(minute=20, hour=3),
            "options": {"queue": "celery"},
        },
        "process-event-risk-every-5min": {
            "task": "app.tasks.event_risk.process_event_risk_task",
            "schedule": crontab(minute="*/5"),
            "options": {"queue": "celery"},
        },
        "process-news-impact-feedback-hourly": {
            "task": "app.tasks.event_risk.process_news_impact_feedback_task",
            "schedule": crontab(minute=45, hour="*"),
            "options": {"queue": "celery"},
        },
        "process-liquidity-monitor-every-2min": {
            "task": "app.tasks.liquidity.process_liquidity_monitor_task",
            "schedule": crontab(minute="*/2"),
            "options": {"queue": "celery"},
        },
        "stress-harness-daily": {
            "task": "app.tasks.stress_harness.run_daily_stress_task",
            "schedule": crontab(minute=0, hour=7),
            "options": {"queue": "celery"},
        },
        "grid-bot-tick-every-minute": {
            "task": "app.tasks.grid.tick_grid_bots_task",
            "schedule": crontab(minute="*"),
            "options": {"queue": "celery"},
        },
        "strategy-bots-tick-every-minute": {
            "task": "app.tasks.strategy_bots.tick_strategy_bots_task",
            "schedule": crontab(minute="*"),
            "options": {"queue": "celery"},
        },
        "weekly-backtest-analysis": {
            "task": "app.tasks.backtest_analysis.run_weekly_analysis_task",
            "schedule": crontab(minute=30, hour=6, day_of_week=1),
            "options": {"queue": "backtest"},
        },
        "refresh-daily-forecasts": {
            "task": "app.tasks.forecast.refresh_daily_forecasts_task",
            "schedule": crontab(minute=0, hour=5),
            "options": {"queue": "celery"},
        },
        "emit-forecast-log-basket-daily": {
            "task": "app.tasks.forecast_log.emit_forecast_log_basket_task",
            "schedule": crontab(minute=10, hour=5),
            "options": {"queue": "celery"},
        },
        "settle-forecast-log-daily": {
            "task": "app.tasks.forecast_log.settle_forecast_log_task",
            "schedule": crontab(minute=40, hour=21),
            "options": {"queue": "celery"},
        },
        "snapshot-forecast-log-daily": {
            "task": "app.tasks.forecast_log.snapshot_forecast_log_task",
            "schedule": crontab(minute=50, hour=21),
            "options": {"queue": "celery"},
        },
        "resolve-forecast-snapshots-hourly": {
            "task": "app.tasks.forecast.resolve_forecast_snapshots_task",
            "schedule": crontab(minute=30, hour="*"),
            "options": {"queue": "celery"},
        },
        "realize-daily-book-after-close": {
            "task": "app.tasks.forecast.realize_daily_book_task",
            "schedule": crontab(minute=20, hour=21),
            "options": {"queue": "celery"},
        },
        "daily-forecast-model-retrain": {
            "task": "app.tasks.forecast.retrain_forecast_models_task",
            "schedule": crontab(minute=0, hour=4),
            "options": {"queue": "celery"},
        },
        "register-forecast-baseline-daily": {
            "task": "app.tasks.forecast.register_live_baseline_task",
            "schedule": crontab(minute=40, hour=5),
            "options": {"queue": "celery"},
        },
        "macro-registry-daily-refresh": {
            "task": "app.tasks.macro_registry.macro_daily_refresh_task",
            "schedule": crontab(minute=0, hour=8),
            "options": {"queue": "ingestion"},
        },
        "macro-registry-weekly-report": {
            "task": "app.tasks.macro_registry.macro_weekly_report_task",
            "schedule": crontab(minute=0, hour=6, day_of_week=1),
            "options": {"queue": "celery"},
        },
        "macro-registry-event-driven-refresh": {
            "task": "app.tasks.macro_registry.macro_event_driven_refresh_task",
            "schedule": crontab(minute="*/30"),
            "options": {"queue": "ingestion"},
        },
        "macro-registry-compact-storage": {
            "task": "app.tasks.macro_registry.compact_macro_storage_task",
            "schedule": crontab(minute=0, hour=3, day_of_month=1),
            "options": {"queue": "ingestion"},
        },
        # MOEX closes are final ~19:00 MSK; US closes ~00:00 MSK. 01:30 UTC catches both.
        "price-history-nightly": {
            "task": "app.tasks.price_history.sync_price_history_task",
            "schedule": crontab(minute=30, hour=1),
            "options": {"queue": "ingestion"},
        },
        "price-history-evening-moex": {
            "task": "app.tasks.price_history.sync_price_history_task",
            "schedule": crontab(minute=10, hour=16),
            "options": {"queue": "ingestion"},
        },
        "macro-registry-seed": {
            "task": "app.tasks.macro_registry.macro_seed_registry_task",
            "schedule": crontab(minute=15, hour=4),
            "options": {"queue": "ingestion"},
        },
        # Daily full market-intelligence pipeline (09:00 UTC).
        # Runs after morning macro refresh (08:00–08:30 UTC) and hourly ingestion.
        # skip_auto_execute=True in task — maneuvers stay PENDING for operator approval.
        "run-market-pipeline-daily": {
            "task": "app.tasks.pipeline.run_scheduled_pipeline_task",
            "schedule": crontab(minute=0, hour=9),
            "options": {"queue": "pipeline"},
        },
        "expire-access-trials-hourly": {
            "task": "access_policy.expire_trials_task",
            "schedule": crontab(minute=5, hour="*"),
            "options": {"queue": "celery"},
        },
        "watchlist-threshold-alerts": {
            "task": "app.tasks.alerts.check_watchlist_alerts_task",
            "schedule": crontab(minute="*/15"),
            "options": {"queue": "celery"},
        },
        "poll-conditional-orders-every-30s": {
            "task": "app.tasks.orders.poll_conditional_orders_task",
            "schedule": 30.0,
            "options": {"queue": "execution"},
        },
        "scan-barrier-closes-every-15s": {
            "task": "app.tasks.position_audit.scan_barrier_closes_task",
            "schedule": 15.0,
            "options": {"queue": "execution"},
        },
        "tick-robot-levels-every-15s": {
            "task": "app.tasks.robot.tick_robot_levels_task",
            "schedule": 15.0,
            "options": {"queue": "execution"},
        },
        "sync-robot-funding-every-4h": {
            "task": "app.tasks.robot.sync_funding_task",
            "schedule": crontab(minute=20, hour="*/4"),
            "options": {"queue": "celery"},
        },
        "sync-venue-fees-daily": {
            "task": "app.tasks.robot.sync_venue_fees_task",
            "schedule": crontab(minute=40, hour=3),
            "options": {"queue": "celery"},
        },
        "check-position-audit-triggers-minutely": {
            "task": "app.tasks.position_audit.check_audit_triggers_task",
            "schedule": 60.0,
            "options": {"queue": "celery"},
        },
        "hourly-health-reporter": {
            "task": "app.tasks.health_reporter.run_hourly_health_report_task",
            "schedule": crontab(minute=12, hour="*"),
            "options": {"queue": "celery"},
        },
        "nightly-paper-live-parity": {
            "task": "app.tasks.execution.nightly_paper_live_parity_task",
            "schedule": crontab(minute=25, hour=2),
            "options": {"queue": "celery"},
        },
        "nightly-ops-dr": {
            "task": "app.tasks.execution.nightly_ops_dr_task",
            "schedule": crontab(minute=30, hour=2),
            "options": {"queue": "celery"},
        },
        "nightly-platform-desk": {
            "task": "app.tasks.execution.nightly_platform_task",
            "schedule": crontab(minute=35, hour=2),
            "options": {"queue": "celery"},
        },
    },
)