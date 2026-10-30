"""GA16-319: empty size_pct must not become 100% of the position."""
from __future__ import annotations

from app.services.robot.monitor import parse_exit_size_pct


def test_ga16_319_empty_size_pct_is_none():
    assert parse_exit_size_pct({}) is None
    assert parse_exit_size_pct({"size_pct": None}) is None
    assert parse_exit_size_pct({"size_pct": ""}) is None
    assert parse_exit_size_pct({"size_pct": 0}) is None
    assert parse_exit_size_pct({"size_pct": "bad"}) is None


def test_ga16_319_explicit_size_pct_ok():
    assert parse_exit_size_pct({"size_pct": 100.0}) == 100.0
    assert parse_exit_size_pct({"size_pct": 50}) == 50.0
    assert parse_exit_size_pct({"size_pct": "25.5"}) == 25.5
