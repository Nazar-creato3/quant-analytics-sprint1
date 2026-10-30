"""Pipeline tracker Redis persistence and status DB fallback."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.utils import pipeline_tracker as pt


@pytest.fixture(autouse=True)
def _clean_tracker():
    pt.reset_store()
    pt.reset_redis_client()
    yield
    pt.reset_store()
    pt.reset_redis_client()


def test_track_run_persists_to_redis():
    fake_redis = MagicMock()
    fake_redis.ping.return_value = True
    store: dict[str, str] = {}

    def _setex(key, ttl, value):
        store[key] = value

    def _get(key):
        return store.get(key)

    fake_redis.setex.side_effect = _setex
    fake_redis.get.side_effect = _get

    with patch.object(pt, "_get_redis", return_value=fake_redis):
        pt.reset_store()
        pt.track_run("run-redis-1", "task-1", triggered_by="api")

        pt.reset_store()
        meta = pt.get_run("run-redis-1")

    assert meta is not None
    assert meta["run_id"] == "run-redis-1"
    assert meta["task_id"] == "task-1"
    assert meta["status"] == "queued"


def test_mark_complete_visible_after_memory_clear():
    fake_redis = MagicMock()
    fake_redis.ping.return_value = True
    store: dict[str, str] = {}

    def _setex(key, ttl, value):
        store[key] = value

    def _get(key):
        return store.get(key)

    fake_redis.setex.side_effect = _setex
    fake_redis.get.side_effect = _get

    with patch.object(pt, "_get_redis", return_value=fake_redis):
        pt.track_run("run-redis-2", "task-2", triggered_by="api")
        pt.mark_complete("run-redis-2", "report-abc")
        pt.reset_store()
        meta = pt.get_run("run-redis-2")

    assert meta is not None
    assert meta["status"] == "complete"
    assert meta["report_id"] == "report-abc"


@pytest.mark.asyncio
async def test_report_id_for_pipeline_run(monkeypatch):
    from app.api.v1.endpoints import pipeline as pipeline_ep

    class _FakeResult:
        def __init__(self, value):
            self._value = value

        def scalar_one_or_none(self):
            return self._value

    async def fake_execute(_stmt):
        return _FakeResult("report-db-1")

    db = MagicMock()
    db.execute = fake_execute

    report_id = await pipeline_ep._report_id_for_pipeline_run(db, "run-db-1", "user-1")
    assert report_id == "report-db-1"


@pytest.mark.asyncio
async def test_foreign_pipeline_run_does_not_leak_report(monkeypatch):
    """AUD-Мозг-01: another user's run_id must not return their report or error."""
    from types import SimpleNamespace

    from app.api.v1.endpoints import pipeline as pipeline_ep

    bob = SimpleNamespace(id="user-b", email="bob@test.com")

    async def fake_user(_db, _email):
        return bob

    async def no_report(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        "app.services.portfolio.user_scope.get_user_by_email",
        fake_user,
    )
    monkeypatch.setattr(
        "app.utils.pipeline_tracker.get_run",
        lambda _run_id: {
            "status": "complete",
            "report_id": "secret-report",
            "task_id": "task-alice",
            "triggered_by": "alice@test.com",
            "error": "alice book",
        },
    )
    monkeypatch.setattr(pipeline_ep, "_report_id_for_pipeline_run", no_report)

    resp = await pipeline_ep.get_pipeline_status("run-alice", email="bob@test.com", db=MagicMock())

    assert resp.status == "unknown"
    assert resp.report_id is None
    assert resp.task_id is None
    assert "secret-report" not in resp.message
    assert "alice" not in resp.message


@pytest.mark.asyncio
async def test_own_pipeline_run_still_returns_report(monkeypatch):
    from types import SimpleNamespace

    from app.api.v1.endpoints import pipeline as pipeline_ep

    alice = SimpleNamespace(id="user-a", email="alice@test.com")

    async def fake_user(_db, _email):
        return alice

    async def counts(*_args, **_kwargs):
        return 2, 10

    monkeypatch.setattr(
        "app.services.portfolio.user_scope.get_user_by_email",
        fake_user,
    )
    monkeypatch.setattr(
        "app.utils.pipeline_tracker.get_run",
        lambda _run_id: {
            "status": "complete",
            "report_id": "report-alice",
            "task_id": "task-alice",
            "triggered_by": "alice@test.com",
        },
    )
    monkeypatch.setattr(pipeline_ep, "_pipeline_status_counts", counts)

    resp = await pipeline_ep.get_pipeline_status("run-alice", email="alice@test.com", db=MagicMock())

    assert resp.status == "complete"
    assert resp.report_id == "report-alice"
    assert resp.tradeable_count == 2
