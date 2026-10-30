"""GA16-346: robot API errors must be Russian without User not found."""

from pathlib import Path


def test_robot_endpoint_client_copy_russian():
    text = Path("app/api/v1/endpoints/robot.py").read_text(encoding="utf-8")
    assert "User not found" not in text
    assert "Plan not found" not in text
    assert "Пользователь не найден" in text
    assert "План не найден" in text
