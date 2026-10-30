"""GA16-327: crypto-stack failures must not leak exception class names."""
from __future__ import annotations

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints.crypto_stack import router
from app.core.deps import get_current_user_email


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_current_user_email] = lambda: "user@example.test"
    return app


def test_ticker_failure_hides_exception_class() -> None:
    with patch(
        "app.api.v1.endpoints.crypto_stack.fetch_ticker",
        side_effect=RuntimeError("secret host"),
    ):
        with TestClient(_app(), raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/crypto-stack/ticker")
    assert resp.status_code == 502
    assert resp.json()["detail"] == "Нет данных"
    assert "RuntimeError" not in resp.text
    assert "secret" not in resp.text.lower()
