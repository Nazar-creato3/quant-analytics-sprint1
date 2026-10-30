from __future__ import annotations

from app.services.fund_report.islands import attach_islands, goal_block
from app.services.goals.service import explain_goal
from app.services.qa.feature_flags import reset_for_tests, set_global


def setup_function() -> None:
    reset_for_tests()
    set_global("qa_goals", True)
    set_global("qa_factor_lens", True)
    set_global("qa_key_rate", True)
    set_global("qa_futures_risk", True)
    set_global("qa_bonds", True)
    set_global("qa_payouts", True)
    set_global("qa_fund_lookthrough", True)
    set_global("qa_position_liquidity", True)


def teardown_function() -> None:
    reset_for_tests()


def test_goal_without_target_explains() -> None:
    block = goal_block(user_id="nobody-goal", mode="paper")
    assert block["status"] == "нет данных"
    assert "цель не задана" in str(block["reason"])


def test_goal_after_explain_has_probability(monkeypatch) -> None:
    import numpy as np

    # a real book: positive NAV and a return series (an empty book no longer gets a synthetic goal)
    monkeypatch.setattr("app.services.goals.service._nav_rub", lambda *_a, **_k: 500_000.0)
    monkeypatch.setattr(
        "app.services.goals.service._daily_returns",
        lambda *_a, **_k: np.random.default_rng(7).normal(0.0004, 0.012, size=252),
    )
    explain_goal("island-u", target_amount=1_000_000, target_date="2030-01-01", mode="paper")
    block = goal_block(user_id="island-u", mode="paper")
    assert block["probability"] is not None
    assert block["reason"]


def test_flag_off_reason() -> None:
    set_global("qa_factor_lens", False)
    out = attach_islands(user_id="x", mode="paper")
    assert out["factors"]["status"] == "нет данных"
    assert out["factors"]["reason"] == "нет данных"
    assert "qa_" not in str(out["factors"]["reason"])


def test_vyiplaty_blocks_have_reason() -> None:
    out = attach_islands(user_id="x", mode="paper")
    for key in ("bonds", "income", "look_through", "liquidity"):
        assert out[key].get("reason")
        assert out[key].get("status") != "будет доступно"
