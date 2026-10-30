"""Prompt 49: public accuracy matches the journal and invents nothing when it is empty."""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from app.services.forecast_log.hash_chain import snapshot_hash
from app.services.forecast_log.record import record_emission
from app.services.forecast_log.settle import settle_row
from app.services.forecast_log.store import get_store
from app.services.forecast_log.summary import internal_summary
from app.services.market_data.eod import EodRow
from app.services.public_accuracy.service import public_accuracy, verify_journal
from app.services.qa.feature_flags import is_enabled, reset_for_tests
from app.services.subscription_billing.service import quote
from app.services.waitlist.service import join
from app.services.waitlist.service import reset as reset_waitlist

FORBIDDEN = ("рекомендуем", "советуем", "подходит вам", "соответствует вашему профилю", "купите", "продайте")


def setup_function() -> None:
    reset_for_tests()
    get_store().reset()
    reset_waitlist()


def teardown_function() -> None:
    reset_for_tests()
    get_store().reset()
    reset_waitlist()


def test_empty_journal_is_not_a_number() -> None:
    assert is_enabled("qa_public_accuracy") is True
    assert is_enabled("qa_preorder") is False
    assert is_enabled("qa_act_live") is False
    assert is_enabled("qa_partners") is False
    assert quote(user_id="p49", plan="personal", period="month")["amount"] == "10000"
    blocked = join(email="a@example.com", name=None, broker="unset", portfolio_range="нет данных", consent=True, honeypot="")
    assert blocked["status"] == "rejected"
    view = public_accuracy()
    assert view["accuracy"] == "нет данных"
    assert view["ci_low"] == "нет данных"
    assert view["naive"] == "нет данных"
    assert view["by_instrument"] == "нет данных"
    assert view["weak_periods"] == "нет данных"
    assert view["updated"] == "нет данных"
    assert view["emissions"] == "0"
    assert view["digest"] == snapshot_hash([])
    assert verify_journal(view["digest"]) is True
    assert verify_journal("0" * 64) is False


def test_public_horizon_matches_internal_summary() -> None:
    row = record_emission(
        ticker="SBER",
        instrument_id="SBER",
        horizon_days=1,
        direction=1,
        probability="0.60",
        section="forecast",
        model_id="p49",
        model_version="v1",
        issued_price="100",
        issued_price_source="test",
        issued_at=datetime(2024, 1, 1, tzinfo=UTC),
    )
    assert row is not None
    settle_row(
        row.id,
        Decimal(100),
        1,
        EodRow(
            instrument_id="SBER",
            session_date=date(2024, 1, 2),
            official_close=Decimal(110),
            last_close=Decimal(999),
            volume=Decimal(1),
            source="iss_moex",
            board="TQBR",
            license_tag="internal_only",
            as_of=date(2024, 1, 2),
        ),
    )
    view = public_accuracy()
    internal = internal_summary()["horizons"][0]
    assert view["horizons"][0]["accuracy"] == str(internal["accuracy"])
    assert view["horizons"][0]["n"] == str(internal["n"])
    assert view["horizons"][0]["hits"] == str(internal["hits"])
    assert view["horizons"][0]["naive_accuracy"] == str(internal["naive_accuracy"])
    assert view["by_instrument"] == "нет данных"
    assert verify_journal(view["digest"]) is True


def test_accuracy_texts_omit_forbidden_phrases() -> None:
    root = Path(__file__).resolve().parents[3]
    text = (root / "backend" / "app" / "services" / "public_accuracy" / "service.py").read_text(encoding="utf-8").lower()
    for phrase in FORBIDDEN:
        assert phrase not in text
    assert "accuracy = 0" not in text
    index = (root / "docs" / "methodology" / "public-index.md").read_text(encoding="utf-8")
    for name in ("risk.md", "returns.md", "maneuver-control.md"):
        assert (root / "docs" / "methodology" / name).is_file()
        assert name in index
