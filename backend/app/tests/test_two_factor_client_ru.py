"""GA16-356: 2FA errors without User not found."""

from pathlib import Path


def test_two_factor_no_user_not_found():
    text = Path("app/api/v1/endpoints/two_factor.py").read_text(encoding="utf-8")
    assert "User not found" not in text
    assert "Пользователь не найден" in text
