"""Celery task registration smoke tests."""
from __future__ import annotations


def test_event_risk_and_liquidity_beat_entries() -> None:
    from app.tasks.celery_app import celery_app

    beat = celery_app.conf.beat_schedule
    assert beat["process-event-risk-every-5min"]["task"] == "app.tasks.event_risk.process_event_risk_task"
    assert beat["process-liquidity-monitor-every-2min"]["task"] == "app.tasks.liquidity.process_liquidity_monitor_task"


def test_fleet_audit_beat_entry() -> None:
    from app.tasks.celery_app import celery_app
    import app.tasks.fleet_audit  # noqa: F401

    entry = celery_app.conf.beat_schedule["refresh-admin-fleet-audit-nightly"]
    assert entry["task"] == "app.tasks.fleet_audit.refresh_fleet_audit_task"
    assert entry["options"]["queue"] == "celery"
    assert "app.tasks.fleet_audit.refresh_fleet_audit_task" in celery_app.tasks


def test_pipeline_task_is_registered() -> None:
    from app.tasks.celery_app import celery_app
    import app.tasks.pipeline  # noqa: F401 — side-effect: registers tasks

    assert "app.tasks.pipeline.run_pipeline_task" in celery_app.tasks


def test_equity_eod_beat_entry() -> None:
    from app.tasks.celery_app import celery_app
    import app.tasks.equity_eod  # noqa: F401

    entry = celery_app.conf.beat_schedule["sync-equity-eod-nightly"]
    assert entry["task"] == "app.tasks.equity_eod.sync_equity_eod_task"
    assert "app.tasks.equity_eod.sync_equity_eod_task" in celery_app.tasks


def test_fred_bulk_beat_entry() -> None:
    from app.tasks.celery_app import celery_app
    import app.tasks.fred_bulk  # noqa: F401

    entry = celery_app.conf.beat_schedule["sync-fred-bulk-nightly"]
    assert entry["task"] == "app.tasks.fred_bulk.sync_fred_bulk_task"
    assert entry["options"]["queue"] == "ingestion"
    assert "app.tasks.fred_bulk.sync_fred_bulk_task" in celery_app.tasks


def test_stooq_bulk_beat_entry() -> None:
    from app.tasks.celery_app import celery_app
    import app.tasks.stooq_bulk  # noqa: F401

    entry = celery_app.conf.beat_schedule["sync-stooq-bulk-nightly"]
    assert entry["task"] == "app.tasks.stooq_bulk.sync_stooq_bulk_task"
    assert entry["options"]["queue"] == "ingestion"
    assert "app.tasks.stooq_bulk.sync_stooq_bulk_task" in celery_app.tasks


def test_ingestion_tasks_are_registered() -> None:
    from app.tasks.celery_app import celery_app
    import app.tasks.data_ingestion  # noqa: F401

    assert "app.tasks.data_ingestion.ingest_news_task" in celery_app.tasks


def test_pipeline_task_routes_to_pipeline_queue() -> None:
    from app.tasks.celery_app import celery_app

    routes = celery_app.conf.task_routes or {}
    assert routes.get("app.tasks.pipeline.*", {}).get("queue") == "pipeline"


def test_grid_tick_task_routes_to_celery_queue() -> None:
    from app.tasks.celery_app import celery_app
    import app.tasks.grid  # noqa: F401

    routes = celery_app.conf.task_routes or {}
    assert routes.get("app.tasks.grid.*", {}).get("queue") == "celery"
    assert (
        celery_app.conf.beat_schedule["grid-bot-tick-every-minute"]["options"]["queue"]
        == "celery"
    )


def test_realize_daily_book_beat_entry() -> None:
    from app.tasks.celery_app import celery_app
    import app.tasks.forecast  # noqa: F401

    entry = celery_app.conf.beat_schedule["realize-daily-book-after-close"]
    assert entry["task"] == "app.tasks.forecast.realize_daily_book_task"
    assert "app.tasks.forecast.realize_daily_book_task" in celery_app.tasks


def test_scheduled_pipeline_beat_entry() -> None:
    from app.tasks.celery_app import celery_app
    import app.tasks.pipeline  # noqa: F401

    entry = celery_app.conf.beat_schedule["run-market-pipeline-daily"]
    assert entry["task"] == "app.tasks.pipeline.run_scheduled_pipeline_task"
    assert entry["options"]["queue"] == "pipeline"


def test_scheduled_pipeline_task_uses_manual_approval_mode(monkeypatch) -> None:
    from app.tasks import pipeline as pipeline_mod

    captured: dict = {}

    def _fake_dispatch(**kwargs):
        captured.update(kwargs)
        return "task-fake-1"

    async def _fake_eligible_users(_session):
        from types import SimpleNamespace

        return [SimpleNamespace(id="user-1", email="scheduled@test.com")]

    async def _fake_watchlist(_session, _email):
        return ["AAPL"]

    async def _fake_portfolio(_email, _db=None):
        return 100_000.0

    async def _fake_threshold(_email):
        return 0.55

    monkeypatch.setattr(
        "app.utils.pipeline_dispatch.dispatch_pipeline_task",
        _fake_dispatch,
    )
    monkeypatch.setattr(
        "app.services.pipeline.eligible_users.list_pipeline_eligible_users",
        _fake_eligible_users,
    )
    monkeypatch.setattr(
        "app.services.settings.watchlist.get_effective_watchlist",
        _fake_watchlist,
    )
    monkeypatch.setattr(
        "app.services.portfolio.metrics._user_effective_deploy_cap",
        _fake_portfolio,
    )
    monkeypatch.setattr(
        "app.services.portfolio.metrics._user_confidence_threshold",
        _fake_threshold,
    )
    monkeypatch.setattr(
        "app.utils.pipeline_tracker.track_run",
        lambda *args, **kwargs: None,
    )

    result = pipeline_mod.run_scheduled_pipeline_task()

    assert captured.get("skip_auto_execute") is True
    assert str(captured.get("triggered_by", "")).startswith("beat:")
    assert result["status"] == "queued"
    assert result["skip_auto_execute"] is True


def test_pipeline_imports_maneuver_exposure_from_exposure_module() -> None:
    """Regression: exposure helpers moved out of metrics.py in 3ccd328."""
    import inspect

    from app.services.portfolio.exposure import maneuver_exposure
    import app.tasks.pipeline as pipeline_mod

    source = inspect.getsource(pipeline_mod._async_pipeline)
    assert "from app.services.portfolio.exposure import maneuver_exposure" in source
    assert "_maneuver_exposure" not in source
    assert "from app.services.portfolio.metrics import _maneuver_exposure" not in source
    assert callable(maneuver_exposure)


def test_position_audit_tasks_registered() -> None:
    from app.tasks.celery_app import celery_app
    import app.tasks.position_audit  # noqa: F401

    beat = celery_app.conf.beat_schedule
    assert beat["check-position-audit-triggers-minutely"]["task"] == (
        "app.tasks.position_audit.check_audit_triggers_task"
    )
    assert beat["check-position-audit-triggers-minutely"]["schedule"] == 60.0
    assert "app.tasks.position_audit.run_position_audit_task" in celery_app.tasks


def test_hourly_health_reporter_beat_entry() -> None:
    from app.tasks.celery_app import celery_app
    import app.tasks.health_reporter  # noqa: F401

    beat = celery_app.conf.beat_schedule
    entry = beat["hourly-health-reporter"]
    assert entry["task"] == "app.tasks.health_reporter.run_hourly_health_report_task"
    assert entry["options"]["queue"] == "celery"
    assert "app.tasks.health_reporter.run_hourly_health_report_task" in celery_app.tasks


def test_strategy_bots_task_is_registered() -> None:
    from app.tasks.celery_app import celery_app
    import app.tasks.strategy_bots  # noqa: F401

    beat = celery_app.conf.beat_schedule
    assert beat["strategy-bots-tick-every-minute"]["task"] == (
        "app.tasks.strategy_bots.tick_strategy_bots_task"
    )
    assert "app.tasks.strategy_bots.tick_strategy_bots_task" in celery_app.tasks
