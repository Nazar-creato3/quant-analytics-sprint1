"""GA16-343: application verify/approve texts Russian without str(exc)."""

from pathlib import Path


def test_applications_verify_approve_russian():
    text = Path("app/api/v1/endpoints/applications.py").read_text(encoding="utf-8")
    assert "Too many attempts" not in text
    assert "Invalid or expired verification link" not in text
    assert "Application not found" not in text
    assert "str(exc)" not in text
    assert "Слишком много попыток" in text
    assert "Ссылка недействительна или устарела" in text
    assert "Заявка не найдена" in text
    assert "Сейчас заявку одобрить нельзя." in text
