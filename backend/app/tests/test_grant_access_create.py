"""grant_access --create asks for the password twice and never accepts a weak one."""
from __future__ import annotations

import pytest

from app.scripts import grant_access


def _answers(monkeypatch, *values):
    it = iter(values)
    monkeypatch.setattr("getpass.getpass", lambda _prompt="": next(it))


def test_password_confirmed(monkeypatch):
    _answers(monkeypatch, "expert-pass-1", "expert-pass-1")
    assert grant_access._ask_password() == "expert-pass-1"


def test_password_mismatch_stops(monkeypatch):
    _answers(monkeypatch, "expert-pass-1", "expert-pass-2")
    with pytest.raises(SystemExit):
        grant_access._ask_password()


def test_short_password_stops(monkeypatch):
    _answers(monkeypatch, "short")
    with pytest.raises(SystemExit):
        grant_access._ask_password()
