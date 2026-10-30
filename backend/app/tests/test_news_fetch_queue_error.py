"""GA16-328: news fetch queue failures must not leak exception text."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints.watchlist_news import news_router
from app.core.deps import get_current_user_email, get_db


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(news_router, prefix="/api/v1")
    app.dependency_overrides[get_current_user_email] = lambda: "user@example.test"

    async def _db():
        yield AsyncMock()

    app.dependency_overrides[get_db] = _db
    return TestClient(app, raise_server_exceptions=False)


def test_news_fetch_queue_error_is_generic(client: TestClient) -> None:
    with (
        patch(
            "app.services.settings.watchlist.get_effective_watchlist",
            new=AsyncMock(return_value=["SBER"]),
        ),
        patch(
            "app.tasks.data_ingestion.ingest_news_task",
            MagicMock(delay=MagicMock(side_effect=RuntimeError("redis://secret:6379"))),
        ),
    ):
        resp = client.post("/api/v1/news/fetch")
    assert resp.status_code == 503
    assert resp.json()["detail"] == "Нет данных"
    assert "redis" not in resp.text.lower()
    assert "secret" not in resp.text.lower()
