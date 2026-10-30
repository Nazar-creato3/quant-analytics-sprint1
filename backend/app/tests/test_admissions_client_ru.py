"""GA16-354: CRM admissions refusals must be Russian."""

from pathlib import Path


def test_admissions_crm_refusals_russian():
    text = Path("app/api/v1/endpoints/admissions.py").read_text(encoding="utf-8")
    assert "CRM access denied" not in text
    assert "CRM write denied" not in text
    assert "str(exc)" not in text
    assert "Нет доступа к заявкам" in text
    assert "Нет прав изменять заявки" in text
