"""GA16-341: deal intent API errors must be Russian without User/DealIntent jargon."""

from pathlib import Path


def test_deal_intents_client_copy_russian():
    text = Path("app/api/v1/endpoints/deal_intents.py").read_text(encoding="utf-8")
    assert "User not found" not in text
    assert "DealIntent not found" not in text
    assert "detail=str(exc)" not in text
    assert "Пользователь не найден" in text
    assert "Намерение не найдено" in text
    assert "Сейчас это действие недоступно." in text
