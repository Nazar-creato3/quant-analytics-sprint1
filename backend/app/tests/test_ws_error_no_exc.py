"""GA16-253: websocket error payloads must not include exception text."""
from __future__ import annotations

from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "api" / "v1" / "endpoints" / "websocket.py"


def test_ws_client_errors_are_generic() -> None:
    text = SRC.read_text(encoding="utf-8")
    assert '_WS_ERR = "нет данных"' in text
    assert "failed: {exc}" not in text
    assert '"message": f"Price fetch failed' not in text
    assert '"message": _WS_ERR' in text
