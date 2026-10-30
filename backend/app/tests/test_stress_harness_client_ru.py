"""GA16-340: stress harness client copy and no invented portfolio value."""

from pathlib import Path

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints.stress_harness import _reject_invented_portfolio_value


def test_reject_invented_portfolio_value():
    _reject_invented_portfolio_value(None)
    with pytest.raises(HTTPException) as exc:
        _reject_invented_portfolio_value(250_000.0)
    assert exc.value.status_code == 422
    assert "книги" in exc.value.detail


def test_stress_harness_endpoint_copy_is_russian():
    text = Path("app/api/v1/endpoints/stress_harness.py").read_text(encoding="utf-8")
    assert "User not found" not in text
    assert "No open portfolio positions" not in text
    assert "Пользователь не найден" in text
    assert "Нет открытых позиций для стресс-теста." in text
