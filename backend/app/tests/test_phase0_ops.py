"""Prompt 02 contracts: T-Invest app name, secret redaction, hosting reminder."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from app.core.config import Settings
from app.core.logging import drop_secret_keys
from app.services.ops.hosting_quota import days_until_paid, reminder_due


def test_tinkoff_app_name_is_quant_analytics():
    assert Settings.model_fields["TINKOFF_APP_NAME"].default == "QuantAnalytics"


def test_secrets_backend_is_env():
    assert Settings.model_fields["SECRETS_BACKEND"].default == "env"


def test_drop_secret_keys_redacts_credentials():
    event = drop_secret_keys(
        None,  # type: ignore[arg-type]
        "info",
        {"secret_key": "super-secret", "password": "p", "ok": "visible"},
    )
    assert event["secret_key"] == "[redacted]"
    assert event["password"] == "[redacted]"
    assert event["ok"] == "visible"


def test_railway_toml_removed():
    repo = Path(__file__).resolve().parents[3]
    assert not (repo / "backend" / "railway.toml").exists()
    assert not (repo / "frontend" / "railway.toml").exists()


def test_hosting_reminder_windows():
    today = date(2026, 10, 4)
    assert reminder_due(today, today + timedelta(days=7)) is True
    assert reminder_due(today, today + timedelta(days=3)) is True
    assert reminder_due(today, today + timedelta(days=20)) is False
    assert days_until_paid("", today) is None
