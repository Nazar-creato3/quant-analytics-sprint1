"""GA16-234: access application must not collect a browser fingerprint."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_apply_page_does_not_collect_fingerprint() -> None:
    text = (ROOT / "frontend" / "src" / "app" / "apply" / "page.tsx").read_text(encoding="utf-8")
    assert "getBrowserFingerprint" not in text
    assert "fingerprint" not in text


def test_register_does_not_bind_device_from_body() -> None:
    text = (ROOT / "backend" / "app" / "api" / "v1" / "endpoints" / "auth.py").read_text(encoding="utf-8")
    start = text.find("async def register(")
    end = text.find("\nasync def ", start + 10)
    chunk = text[start:end]
    assert "fingerprint_device" not in chunk
