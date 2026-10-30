"""GA16-352: chat API refusals Russian without chat.read / str(exc)."""

from pathlib import Path


def test_chat_client_errors_russian():
    text = Path("app/api/v1/endpoints/chat.py").read_text(encoding="utf-8")
    assert "chat.read required" not in text
    assert "str(exc)" not in text
    assert "Нет доступа к чату" in text
    assert "Чат не найден" in text
