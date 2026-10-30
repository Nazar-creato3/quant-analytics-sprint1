"""GA16-347: promote errors/responses must not leak recipe names or str(exc)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import platform as plat
from app.core.deps import get_current_user_email, get_user_db


async def _fake_db():
    yield AsyncMock()


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(plat.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user_email] = lambda: "cio@example.com"
    app.dependency_overrides[get_user_db] = _fake_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_promote_error_is_generic(client):
    with patch.object(plat, "_current_user", AsyncMock(return_value=None)):
        with patch.object(plat, "_verify_user_totp", return_value=None):
            with patch(
                "app.services.platform_desk.promotion.promote_with_signoff",
                side_effect=ValueError("refuse promote on label_recipe=evil_recipe"),
            ):
                resp = client.post(
                    "/api/v1/platform/promote",
                    json={"name": "m1", "feature_freeze_id": "fz", "confirm": True, "n_train": 40, "outer_n": 40},
                )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "evil_recipe" not in detail
    assert "label_recipe" not in detail
    assert "triple_barrier" not in detail
    assert "Не удалось" in detail


def test_promote_success_hides_recipe_fields(client):
    raw = {
        "ok": True,
        "model_card": {
            "name": "m1",
            "version": "1",
            "promoted": True,
            "label_recipe": "triple_barrier+meta_label",
            "cv_method": "nested_combinatorial_purged_cv",
        },
        "signoff": {"reviewer": "cio@example.com", "mfa": False},
        "params": {"label_recipe": "triple_barrier+meta_label"},
    }
    with patch.object(plat, "_current_user", AsyncMock(return_value=None)):
        with patch.object(plat, "_verify_user_totp", return_value=None):
            with patch("app.services.platform_desk.promotion.promote_with_signoff", return_value=raw):
                resp = client.post(
                    "/api/v1/platform/promote",
                    json={"name": "m1", "feature_freeze_id": "fz", "confirm": True, "n_train": 40, "outer_n": 40},
                )
    assert resp.status_code == 200
    body = resp.json()
    blob = str(body).lower()
    assert "triple_barrier" not in blob
    assert "nested_combinatorial" not in blob
    assert "label_recipe" not in blob
    assert body["model"]["name"] == "m1"
