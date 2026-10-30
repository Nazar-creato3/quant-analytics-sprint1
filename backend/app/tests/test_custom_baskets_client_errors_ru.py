"""GA16-336: custom basket API errors must be Russian without str(exc)."""

from pathlib import Path

from app.api.v1.endpoints.custom_baskets import _map_service_error
from app.services.custom_basket.service import (
    CustomBasketIntegrityError,
    CustomBasketNotFoundError,
    CustomBasketValidationError,
)


def test_map_service_error_russian_no_raw_exc():
    assert _map_service_error(CustomBasketNotFoundError("x")).detail == "Корзина не найдена"
    assert "x" not in str(_map_service_error(CustomBasketIntegrityError("secret")).detail)
    assert "secret" not in str(
        _map_service_error(CustomBasketValidationError("secret")).detail
    )


def test_user_not_found_is_russian():
    text = Path("app/api/v1/endpoints/custom_baskets.py").read_text(encoding="utf-8")
    assert "User not found" not in text
    assert "Пользователь не найден" in text
