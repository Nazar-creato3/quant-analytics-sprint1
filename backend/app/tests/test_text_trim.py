"""Tests for display-safe rationale trimming."""
from __future__ import annotations

from app.utils.text_trim import strip_incomplete_tail, trim_display_text


def test_trim_display_text_does_not_end_with_macd_colon():
    rationale = (
        "Сигнал от правила-фолбэк (уверенность 80%). "
        "Режим: bull. RSI: 55. MACD: бычий. "
        "Объём: выше среднего (1.4x). Новостной фон: +0.12. R:R = 2.1."
    )
    trimmed = trim_display_text(rationale, 60)
    assert not trimmed.endswith("MACD:")
    assert "MACD:" not in trimmed or trimmed.endswith("…")


def test_trim_display_text_does_not_end_with_partial_novostno():
    rationale = (
        "Сигнал от ML-модель (уверенность 72%). "
        "Режим: range. RSI: 48. MACD: медвежий. "
        "Объём: ниже среднего (0.8x). Новостной фон: -0.05. R:R = 1.8."
    )
    trimmed = trim_display_text(rationale, 120)
    assert not trimmed.endswith("Новостно")
    assert not trimmed.endswith("Новостной фон:")


def test_strip_incomplete_tail_removes_dangling_label():
    assert strip_incomplete_tail("Режим: bull. RSI: 55. MACD:") == "Режим: bull. RSI: 55"
