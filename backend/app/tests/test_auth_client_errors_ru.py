"""GA16-295: login/device client errors are Russian, not exception codes."""

from app.api.v1.endpoints.auth import (
    _GENERIC_DEVICE_FAIL,
    _GENERIC_LOGIN_FAIL,
    _client_error_detail,
)


def test_login_fail_message_is_russian():
    assert "Invalid" not in _GENERIC_LOGIN_FAIL
    assert "email" in _GENERIC_LOGIN_FAIL.lower() or "пароль" in _GENERIC_LOGIN_FAIL


def test_device_error_maps_known_code():
    detail = _client_error_detail(ValueError("max_accounts_per_device"), fallback=_GENERIC_DEVICE_FAIL)
    assert "устройств" in detail.lower()
    assert detail != "max_accounts_per_device"


def test_unknown_device_error_is_generic():
    detail = _client_error_detail(ValueError("SomeInternalCode"), fallback=_GENERIC_DEVICE_FAIL)
    assert detail == _GENERIC_DEVICE_FAIL
    assert "SomeInternalCode" not in detail
