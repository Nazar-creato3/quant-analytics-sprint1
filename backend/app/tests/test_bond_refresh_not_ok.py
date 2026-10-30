"""GA16-270: loading one fixture is not a successful bond refresh."""
from __future__ import annotations

from app.tasks.bonds import refresh_bond_reference_task


def test_fixture_is_not_a_bond_refresh(monkeypatch) -> None:
    monkeypatch.setattr("app.tasks.bonds.ensure_fixtures", lambda: None)
    result = refresh_bond_reference_task()
    assert result["ok"] is False
    assert result["reason"] == "нет данных"
    assert result["refreshed"] == 0
