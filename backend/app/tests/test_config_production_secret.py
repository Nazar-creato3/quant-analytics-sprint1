"""Tests for production SECRET_KEY validation (SEC-07)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import AppEnv, Settings, get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class TestProductionSecretValidation:
    def test_allows_strong_secret_in_production(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv(
            "SECRET_KEY",
            "f4e3d2c1b0a9876543210fedcba9876543210fedcba9876543210ab",
        )
        settings = Settings()
        assert settings.APP_ENV == AppEnv.PRODUCTION
        assert len(settings.SECRET_KEY) >= 32

    def test_rejects_short_secret_in_production(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("SECRET_KEY", "too-short")
        with pytest.raises(ValidationError, match="at least 32 characters"):
            Settings()

    def test_rejects_weak_secret_in_production(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("SECRET_KEY", "ci-test-secret-key-32chars-minimum")
        with pytest.raises(ValidationError, match="weak/default"):
            Settings()

    def test_ci_secret_allowed_in_development(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "development")
        monkeypatch.setenv("SECRET_KEY", "ci-test-secret-key-32chars-minimum")
        settings = Settings()
        assert settings.SECRET_KEY == "ci-test-secret-key-32chars-minimum"
