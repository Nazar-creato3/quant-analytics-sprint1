"""Prompt 27: paper bot, pause, composer handoff, backtest honesty."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from app.services.bot_core.service import (
    create_from_composer,
    cscv_pbo,
    deflated_sharpe,
    event_names,
    leaks,
    list_bots,
    open_paper,
    pause_if_breached,
    request_live,
    reset,
)
from app.services.portfolio_book.service import positions_for
from app.services.qa.feature_flags import is_enabled, reset_for_tests
from app.services.strategy.composer.walk_forward_backtest import _context
from app.services.strategy.types import MarketRegime
from app.services.subscription_billing.service import quote

FORBIDDEN = ("рекомендуем", "советуем", "подходит вам", "соответствует вашему профилю", "купите", "продайте")


def setup_function() -> None:
    reset_for_tests()
    reset()


def teardown_function() -> None:
    reset_for_tests()
    reset()


def test_flags_and_price_stay_closed() -> None:
    assert is_enabled("qa_bot_core") is True
    assert is_enabled("qa_act_live") is False
    assert is_enabled("qa_partners") is False
    assert is_enabled("qa_partner_ads") is False
    assert quote(user_id="p27", plan="personal", period="month")["amount"] == "нет данных"


def test_paper_fill_is_in_the_book_then_pause() -> None:
    user = "p27-paper"
    opened = open_paper(
        user_id=user,
        ticker="SBER",
        qty="2",
        price="100",
        ccy="RUB",
        stop="90",
    )
    assert opened["status"] == "paper"
    assert opened["live"] is False
    assert opened["commission_bps"] == "нет данных"
    rows = [row for row in positions_for(user_id=user, mode="paper") if row.ticker == "SBER"]
    assert rows and str(rows[0].qty) == "2"
    paused = pause_if_breached(bot_id=opened["id"], mark="80")
    assert paused["status"] == "paused"
    assert "bot.paused" in event_names()
    assert "bot.opened" in event_names()
    live = request_live(opened["id"])
    assert live["status"] == "rejected"
    assert live["reason"] == "живая отправка недоступна"


def test_unknown_and_leveraged_names_do_not_fill() -> None:
    missing = open_paper(user_id="p27-miss", ticker="NOTALISTED", qty="1", price="10", ccy="RUB")
    assert missing["status"] == "rejected"
    assert missing["reason"] == "instrument_unavailable"
    assert positions_for(user_id="p27-miss", mode="paper") == []
    perp = open_paper(user_id="p27-perp", ticker="SBER", qty="1", price="10", ccy="RUB", kind="perpetual")
    assert perp["status"] == "rejected"
    assert perp["margin"] == "нет данных"
    blank = open_paper(user_id="p27-blank", ticker="SBER", qty="1", price=None, ccy="RUB")
    assert blank["reason"] == "нет данных"


def test_composer_opens_a_paper_bot() -> None:
    opened = create_from_composer(
        user_id="p27-composer",
        ticker="GAZP",
        regime="range",
        strategy="hold",
        qty="1",
        price="50",
        ccy="RUB",
    )
    assert opened["status"] == "paper"
    assert opened["source"] == "composer"
    assert opened["regime"] == "range"
    assert list_bots("p27-composer")[0]["strategy"] == "hold"
    unknown = create_from_composer(
        user_id="p27-composer",
        ticker="GAZP",
        regime="unknown",
        strategy="hold",
        qty="1",
        price="50",
        ccy="RUB",
    )
    assert unknown["status"] == "нет данных"


def test_lookahead_and_selection_counts() -> None:
    signal = datetime(2026, 10, 7, tzinfo=UTC)
    trade = datetime(2026, 10, 6, tzinfo=UTC)
    assert leaks(signal, trade) is True
    assert leaks(signal, signal) is False
    assert deflated_sharpe(1.0, trials=1, observations=10) == "нет данных"
    assert cscv_pbo([[0.1, 0.2]]) == "нет данных"
    matrix = [
        [0.2, -0.1],
        [0.3, -0.2],
        [-0.4, 0.5],
        [-0.3, 0.4],
    ]
    pbo = cscv_pbo(matrix)
    assert pbo != "нет данных"
    assert len(matrix[0]) == 2
    score = deflated_sharpe(0.2, trials=len(matrix[0]), observations=len(matrix))
    assert score != "нет данных"


def test_walk_forward_does_not_invent_microstructure() -> None:
    ctx = _context(0.2, 0.4, MarketRegime.RANGE, 100.0, "SBER")
    assert ctx.microstructure_score == 0.0


def test_bot_texts_omit_forbidden_phrases() -> None:
    root = Path(__file__).resolve().parents[2]
    text = (root / "app" / "services" / "bot_core" / "service.py").read_text(encoding="utf-8").lower()
    for phrase in FORBIDDEN:
        assert phrase not in text
