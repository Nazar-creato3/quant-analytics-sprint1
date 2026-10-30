"""GA16-326: maneuver edit refusal must be Russian without status enum."""

from pathlib import Path


def test_edit_refusal_has_no_status_enum_in_detail():
    text = Path("app/api/v1/endpoints/maneuvers.py").read_text(encoding="utf-8")
    assert "Maneuver is {maneuver.status}" not in text
    assert "Сейчас этот манёвр нельзя изменить." in text
    assert "cannot edit." not in text
