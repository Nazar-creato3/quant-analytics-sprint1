from app.services.goals.math import bootstrap_terminal
from app.services.goals.service import explain_goal
import numpy as np


def test_zero_return_reaches_current_wealth() -> None:
    r = np.zeros(80)
    out = bootstrap_terminal(r, start=1_000_000, monthly_contrib=0, days=50, target=1_000_000, seed=63)
    assert out["status"] == "ok"
    assert out["probability"] == 1.0


def test_short_series_is_empty() -> None:
    out = bootstrap_terminal(np.array([0.01]), start=1, monthly_contrib=0, days=10, target=2, seed=63)
    assert out["status"] == "нет данных"
    assert out["probability"] is None


def test_empty_book_goal_is_not_synthetic(monkeypatch) -> None:
    monkeypatch.setattr("app.services.goals.service.is_enabled", lambda *_a, **_k: True)
    monkeypatch.setattr("app.services.goals.service._holdings_from_book", lambda *_a, **_k: [])
    monkeypatch.setattr("app.services.goals.service._nav_rub", lambda *_a, **_k: 0.0)
    out = explain_goal("audit-empty-a", target_amount=1_000_000, target_date="2027-10-16")
    assert out["data_status"] == "нет данных"
    assert out["probability"] is None
    assert out.get("p05") is None


def test_down_path_misses_high_target() -> None:
    r = np.full(80, -0.01)
    out = bootstrap_terminal(r, start=100, monthly_contrib=0, days=40, target=10_000, seed=63, n_paths=200)
    assert out["probability"] == 0.0
