"""GA16-355: position audit errors without User not found."""

from pathlib import Path


def test_position_audit_no_user_not_found():
    text = Path("app/api/v1/endpoints/position_audit.py").read_text(encoding="utf-8")
    assert "User not found" not in text
    assert "Пользователь не найден" in text
