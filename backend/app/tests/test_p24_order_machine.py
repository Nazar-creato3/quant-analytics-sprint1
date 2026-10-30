"""Prompt 24: order machine, paper book fill, live stays off. Does not import app.main."""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.order_machine.service import (
    _step,
    add_fill,
    automatic_blocked,
    check_live_limits,
    get_order,
    halt,
    moex_crypto_adapter,
    reconcile,
    relax_live_limits,
    reset,
    submit_order,
    tokenized_form,
    venue_order_adapter,
)
from app.services.portfolio_book.service import positions_for
from app.services.qa.feature_flags import is_enabled, reset_for_tests, set_global
from app.services.venue_adapters.errors import WithdrawKeyRejected

_FORBIDDEN = ("рекомендуем", "советуем", "подходит вам", "соответствует вашему профилю", "купите", "продайте")


def setup_function() -> None:
    reset_for_tests()
    reset()


def teardown_function() -> None:
    reset_for_tests()
    reset()


def test_flags_live_off_and_phrases():
    from pathlib import Path

    assert is_enabled("qa_act_live") is False
    assert is_enabled("qa_moex_crypto") is False
    text = Path(__file__).resolve().parents[1].joinpath("services/order_machine/service.py").read_text(encoding="utf-8").lower()
    for phrase in _FORBIDDEN:
        assert phrase not in text


def test_paper_fill_is_idempotent_and_visible_in_the_book():
    user = "p24-book"
    first = submit_order(
        user_id=user,
        client_order_id="c-sber-1",
        ticker="SBER",
        side="buy",
        qty="2",
        price="10",
        ccy="RUB",
        actor="human",
        confirmed=True,
        maneuver_key="act:m1:v1:f1",
    )
    again = submit_order(
        user_id=user,
        client_order_id="c-sber-1",
        ticker="SBER",
        side="buy",
        qty="2",
        price="10",
        ccy="RUB",
    )
    assert first["status"] == "filled"
    assert again["status"] == "filled"
    assert again["transitions"] == first["transitions"]
    rows = [row for row in positions_for(user_id=user, mode="paper") if row.ticker == "SBER"]
    assert len(rows) == 1
    assert rows[0].qty == Decimal(2)


def test_future_margin_missing_blocks_auto_and_human_sees_no_data():
    blocked = submit_order(
        user_id="p24-fut",
        client_order_id="c-fut-auto",
        ticker="SI-9.24",
        side="buy",
        qty="1",
        price="10",
        ccy="RUB",
        actor="bot",
        instrument_kind="future",
    )
    assert blocked["status"] == "rejected"
    assert blocked["reason"] == "нет данных"
    assert blocked["margin"]["margin"] == "нет данных"
    assert blocked["margin"]["liquidation"] == "нет данных"
    human = submit_order(
        user_id="p24-perp",
        client_order_id="c-perp",
        ticker="SPYF-PERP",
        side="buy",
        qty="1",
        price="10",
        ccy="RUB",
        actor="human",
        confirmed=True,
        instrument_kind="perpetual",
    )
    assert human["status"] == "rejected"
    assert human["reason"] == "instrument_unavailable"
    assert positions_for(user_id="p24-perp", mode="paper") == []
    assert venue_order_adapter("finam")["status"] == "нет данных"


def test_stop_halt_cancels_bot_and_blocks_the_next_one():
    parked = submit_order(
        user_id="p24-halt",
        client_order_id="c-stop",
        ticker="SBER",
        side="sell",
        qty="1",
        price="10",
        ccy="RUB",
        order_type="stop",
        actor="bot",
    )
    assert parked["status"] == "accepted"
    stopped = halt(actor="admin", user_id=None)
    assert "c-stop" in stopped["cancelled"]
    assert get_order("c-stop")["status"] == "cancelled"
    nxt = submit_order(
        user_id="p24-halt",
        client_order_id="c-next",
        ticker="GAZP",
        side="buy",
        qty="1",
        price="10",
        ccy="RUB",
        actor="auto",
    )
    assert nxt["status"] == "rejected"
    assert nxt["reason"] == "halt"
    assert automatic_blocked("p24-halt") is True


def test_partial_fill_then_rest_and_illegal_transition():
    user = "p24-part"
    parked = submit_order(
        user_id=user,
        client_order_id="c-part",
        ticker="GAZP",
        side="buy",
        qty="4",
        price="10",
        ccy="RUB",
        order_type="stop",
        actor="human",
        confirmed=True,
    )
    assert parked["status"] == "accepted"
    partial = add_fill(user_id=user, client_order_id="c-part", qty="1")
    assert partial["status"] == "partial"
    done = add_fill(user_id=user, client_order_id="c-part", qty="3")
    assert done["status"] == "filled"
    assert done["filled_qty"] == "4"
    again = add_fill(user_id=user, client_order_id="c-part", qty="1")
    assert again["filled_qty"] == "4"
    rows = [row for row in positions_for(user_id=user, mode="paper") if row.ticker == "GAZP"]
    assert rows[0].qty == Decimal(4)
    with pytest.raises(ValueError, match="illegal"):
        _step({"status": "filled", "transitions": []}, "sent")


def test_live_flag_limits_reconcile_and_withdraw_key():
    live = submit_order(
        user_id="p24-live",
        client_order_id="c-live-off",
        ticker="SBER",
        side="buy",
        qty="1",
        price="10",
        ccy="RUB",
        mode="live",
        venue="tinkoff",
    )
    assert live["status"] == "rejected"
    assert live["reason"] == "qa_act_live выключен"
    set_global("qa_act_live", True)
    limited = submit_order(
        user_id="p24-live",
        client_order_id="c-live-big",
        ticker="SBER",
        side="buy",
        qty="1000",
        price="1000",
        ccy="RUB",
        mode="live",
        venue="finam",
    )
    assert limited["reason"] == "номинал выше защитного лимита"
    assert relax_live_limits(user_id="p24-live", confirm=False)["status"] == "не изменено"
    assert relax_live_limits(user_id="p24-live", confirm=True)["status"] == "снято"
    assert check_live_limits(user_id="p24-live", notional=Decimal(1000000)) is None
    refused = submit_order(
        user_id="p24-live",
        client_order_id="c-live-finam",
        ticker="SBER",
        side="buy",
        qty="1",
        price="10",
        ccy="RUB",
        mode="live",
        venue="finam",
    )
    assert "Финам" in refused["reason"]
    assert refused["status"] == "rejected"
    missing = reconcile(user_id="p24-live", broker_orders=None)
    assert missing["status"] == "нет данных"
    assert automatic_blocked("p24-live") is True
    with pytest.raises(WithdrawKeyRejected):
        submit_order(
            user_id="p24-key",
            client_order_id="c-key",
            ticker="SBER",
            side="buy",
            qty="1",
            price="10",
            ccy="RUB",
            scopes=["withdraw"],
            venue="finam",
        )
    assert get_order("c-key") is None
    assert tokenized_form("AAPLX")["asset_id"] == "eq:AAPL"
    assert tokenized_form("AAPLX")["execution"] == "нет данных"
    assert moex_crypto_adapter()["status"] == "off"
