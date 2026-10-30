"""GA16-335: feature store status must not expose feast_* names."""
from __future__ import annotations

from app.services.forecast.feature_store import feast_status


def test_feature_store_status_hides_feast_names() -> None:
    body = feast_status()
    blob = str(body).lower()
    assert "feast" not in blob
    assert "requirements-ml" not in blob
    assert "forecast_tech" not in blob
    assert body["ready"] is True
    assert "Хранилище" in body["note"]
