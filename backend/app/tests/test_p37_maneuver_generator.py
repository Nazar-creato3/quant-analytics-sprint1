"""Prompt 37: hypothetical preview and maneuver candidates. No app.main import."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from app.services.act_desk.service import (
    hypothetical_holdings,
    preview_trade,
    propose,
    reset as reset_act,
    save_profile,
)
from app.services.explanations.service import filter_wording
from app.services.maneuvers.service import (
    generate_maneuvers,
    load_maneuver_config,
    maneuver_expired,
    select_maneuvers,
)
from app.services.portfolio_book.service import ensure_account, record_transaction
from app.services.portfolio_book.store import get_book
from app.services.qa.feature_flags import reset_for_tests, set_global
from app.services.risk_engine.series import put_series, reset as reset_series
from app.services.risk_engine.service import compute_risk_for_holdings, invalidate
from app.services.stress_library.service import _reset as reset_stress

GOLDEN = Path(__file__).resolve().parents[3] / "docs" / "qa" / "golden" / "maneuver_two_name.json"
FORBIDDEN = (
    "рекомендуем",
    "советуем",
    "подходит вам",
    "соответствует вашему профилю",
    "купите",
    "продайте",
)


def setup_function() -> None:
    reset_for_tests()
    reset_act()
    get_book().reset()
    reset_series()
    reset_stress()
    invalidate()


def teardown_function() -> None:
    reset_act()
    get_book().reset()
    reset_series()
    reset_stress()
    reset_for_tests()


def _profile(user_id: str = "u-m", **extra: object) -> None:
    answers = {
        "horizon": "3y",
        "risk_tolerance": "moderate",
        "max_position_pct": "0.90",
        "max_crisis_loss_pct": "0.30",
        "expected_return": "0.08",
    }
    answers.update(extra)
    save_profile(user_id, answers)


def _trade(user_id: str, ticker: str, qty: str, amount: str, ext: str, *, when: datetime | None = None) -> None:
    ensure_account(account_id=f"p-{user_id}", user_id=user_id, venue="act", mode="paper")
    record_transaction(
        account_id=f"p-{user_id}",
        user_id=user_id,
        mode="paper",
        venue="act",
        external_id=ext,
        kind="trade",
        instrument_id=ticker,
        ticker=ticker,
        qty=qty,
        amount=amount,
        ccy="RUB",
        event_time=when or datetime(2024, 1, 2, tzinfo=timezone.utc),
    )


def _licensed(monkeypatch, price: str = "100") -> None:
    def _load(ticker: str):
        return Decimal(price), "licensed_test", True

    monkeypatch.setattr("app.services.target_portfolio.service.load_market_price", _load)


def _worst(payload: dict) -> float | None:
    scenarios = payload.get("scenarios") or []
    if not scenarios:
        return None
    return min(float(row.get("pnl_pct") or 0) for row in scenarios)


def test_preview_after_changes_when_trade_changes_the_book() -> None:
    _profile("u-prev")
    _trade("u-prev", "SBER", "10", "1000", "sber")
    market = [0.01 if i % 2 == 0 else -0.02 for i in range(60)]
    put_series("SBER", market)
    put_series("GAZP", [-x for x in market])
    put_series("IMOEX", market)
    preview = preview_trade(user_id="u-prev", ticker="GAZP", qty="10", price="100")
    delta = preview["delta"]
    assert delta["var_95"]["before"] != delta["var_95"]["after"]
    assert delta["es_975"]["before"] != delta["es_975"]["after"]
    assert delta["stress_worst"]["before"] != delta["stress_worst"]["after"]
    assert delta["hhi"]["before"] != delta["hhi"]["after"]


def test_preview_after_matches_risk_service_on_hypothetical_book() -> None:
    _profile("u-bit")
    _trade("u-bit", "SBER", "10", "1000", "sber")
    market = [0.01 if i % 2 == 0 else -0.02 for i in range(60)]
    put_series("SBER", market)
    put_series("GAZP", [-x for x in market])
    put_series("IMOEX", market)
    orders = [{"ticker": "GAZP", "side": "buy", "qty": "10", "price": "100"}]
    holdings = hypothetical_holdings("u-bit", "paper", orders)
    preview = preview_trade(user_id="u-bit", ticker="GAZP", qty="10", price="100")
    risk = compute_risk_for_holdings(holdings)
    assert preview["delta"]["var_95"]["after"] == risk["var_95"]
    assert preview["delta"]["es_975"]["after"] == risk["es_975"]
    assert preview["delta"]["stress_worst"]["after"] == _worst(risk["stress"])


def test_golden_rebalance_orders(monkeypatch) -> None:
    spec = json.loads(GOLDEN.read_text(encoding="utf-8"))
    _licensed(monkeypatch, spec["price"])
    _profile("u-gold", max_position_pct=spec["max_position_pct"])
    for index, row in enumerate(spec["positions"]):
        _trade("u-gold", row["ticker"], row["qty"], row["amount"], f"g{index}")
    batch = generate_maneuvers(user_id="u-gold", mode="paper", method="equal_weight")
    kinds = [item["kind"] for item in batch["items"]]
    assert spec["expected_kind"] in kinds
    found = next(item for item in batch["items"] if item["kind"] == spec["expected_kind"])
    got = [{"ticker": o["ticker"], "side": o["side"], "qty": o["qty"]} for o in found["orders"]]
    assert got == spec["expected_orders"]
    for order in found["orders"]:
        assert order["price"]
        assert order["price_source"]
        assert order["license_tag"]
    assert found["profile_snapshot"]["risk_tolerance"] == "moderate"
    assert found["model_versions"]["maneuvers"] == "maneuvers.v1"
    assert found["model_versions"]["target_portfolio"]
    assert found["expires_at"]
    assert "tax_cash" in json.dumps(found["impact"]["tax"])
    assert filter_wording(found["rationale"]) == []
    assert "это возвращает портфель к вашим правилам" in found["rationale"]


def test_missing_inputs_are_visible() -> None:
    _profile("u-empty")
    batch = generate_maneuvers(user_id="u-empty", mode="paper")
    assert batch["items"] == []
    assert batch["skipped"]
    assert all(row["reason"] == "нет данных" for row in batch["skipped"])
    kinds = {row["kind"] for row in batch["skipped"]}
    assert {"rebalance", "reduce_weight", "risk_limit", "hedge", "tax_loss", "replace", "regime", "deposit"} <= kinds


def test_expiry_by_time_and_price() -> None:
    cfg = load_maneuver_config()
    now = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
    maneuver = {
        "expires_at": (now + timedelta(hours=int(cfg["ttl_hours"]))).isoformat(),
        "expiry": {
            "price_move_pct": format(cfg["price_move_pct"], "f"),
            "anchors": [{"ticker": "SBER", "price": "100"}],
        },
    }
    fresh, _ = maneuver_expired(maneuver, now=now + timedelta(hours=1), prices={"SBER": Decimal("101")})
    assert fresh is False
    late, late_reason = maneuver_expired(
        maneuver, now=now + timedelta(hours=int(cfg["ttl_hours"]) + 1), prices={"SBER": Decimal("100")}
    )
    assert late is True
    assert late_reason == "истёк срок"
    moved, moved_reason = maneuver_expired(maneuver, now=now + timedelta(hours=1), prices={"SBER": Decimal("103")})
    assert moved is True
    assert moved_reason == "цена сдвинулась сверх порога"


def test_conflict_keeps_the_higher_score_and_records_why(monkeypatch) -> None:
    _licensed(monkeypatch)
    _profile("u-conflict", max_position_pct="0.50")
    _trade("u-conflict", "SBER", "80", "8000", "sber")
    _trade("u-conflict", "GAZP", "20", "2000", "gazp", when=datetime(2024, 1, 3, tzinfo=timezone.utc))
    batch = generate_maneuvers(user_id="u-conflict", mode="paper")
    kinds = {item["kind"] for item in batch["items"]}
    assert not ({"rebalance", "reduce_weight"} <= kinds)
    assert any("конфликт" in row["reason"] for row in batch["selection"])
    kept = {row["kept_kind"] for row in batch["selection"]}
    dropped = {row["dropped_kind"] for row in batch["selection"]}
    assert kept & {"rebalance", "reduce_weight"}
    assert dropped & {"rebalance", "reduce_weight"}


def test_cap_records_why_one_was_kept() -> None:
    rows = [
        {"kind": "a", "score": "0.2", "orders": [{"ticker": "AAA"}]},
        {"kind": "b", "score": "0.9", "orders": [{"ticker": "BBB"}]},
        {"kind": "c", "score": "0.1", "orders": [{"ticker": "CCC"}]},
    ]
    kept, notes = select_maneuvers(rows, limit=1)
    assert [row["kind"] for row in kept] == ["b"]
    assert any("N=1" in row["reason"] for row in notes)
    assert all(row["dropped_kind"] != "b" for row in notes)


def test_tax_loss_uses_tax_module_without_a_rate(monkeypatch) -> None:
    def _load(ticker: str):
        return Decimal("50"), "licensed_test", True

    monkeypatch.setattr("app.services.target_portfolio.service.load_market_price", _load)
    _profile("u-tax", max_position_pct="1")
    _trade("u-tax", "SBER", "10", "1000", "sber")
    batch = generate_maneuvers(user_id="u-tax", mode="paper")
    found = next(item for item in batch["items"] if item["kind"] == "tax_loss")
    assert found["orders"][0]["side"] == "sell"
    year = found["impact"]["tax"]["year"]
    assert year["tax_cash"] is None
    assert Decimal(year["net_before_relief"]) < 0
    assert "214.1" in found["rationale"]
    assert "ставка" in year["tax_cash_reason"]
    assert filter_wording(found["rationale"]) == []


def test_hedge_only_when_profile_allows_the_instrument(monkeypatch) -> None:
    _licensed(monkeypatch)
    _profile("u-hedge", max_position_pct="1", allowed_hedge_tickers=["GAZP"])
    _trade("u-hedge", "SBER", "10", "1000", "sber")
    series = [0.01 if i % 2 == 0 else -0.005 for i in range(40)]
    put_series("SBER", series)
    put_series("GAZP", [-x for x in series])
    _profile("u-nohedge", max_position_pct="1")
    _trade("u-nohedge", "SBER", "10", "1000", "sber2")
    put_series("SBER", series)
    without = generate_maneuvers(user_id="u-nohedge", mode="paper")
    assert all(item["kind"] != "hedge" for item in without["items"])
    assert any(row["kind"] == "hedge" and row["reason"] == "нет данных" for row in without["skipped"])
    with_allow = generate_maneuvers(user_id="u-hedge", mode="paper")
    hedge = next(item for item in with_allow["items"] if item["kind"] == "hedge")
    assert hedge["orders"][0]["ticker"] == "GAZP"
    assert hedge["orders"][0]["side"] == "buy"


def test_replace_when_peer_risk_is_lower(monkeypatch) -> None:
    _licensed(monkeypatch)
    _profile("u-repl", max_position_pct="1")
    _trade("u-repl", "SBER", "10", "1000", "sber")
    put_series("SBER", [0.02, -0.03, 0.04, -0.05, 0.03, -0.04, 0.05, -0.02])
    put_series("VTBR", [0.001, -0.001, 0.001, -0.001, 0.001, -0.001, 0.001, -0.001])
    batch = generate_maneuvers(user_id="u-repl", mode="paper")
    found = next(item for item in batch["items"] if item["kind"] == "replace")
    sides = {(order["ticker"], order["side"]) for order in found["orders"]}
    assert ("SBER", "sell") in sides
    assert ("VTBR", "buy") in sides
    assert filter_wording(found["rationale"]) == []


def test_regime_requires_a_real_label(monkeypatch) -> None:
    _licensed(monkeypatch)
    _profile("u-reg", max_position_pct="1")
    _trade("u-reg", "SBER", "10", "1000", "sber")
    quiet = generate_maneuvers(user_id="u-reg", mode="paper")
    assert any(row["kind"] == "regime" and row["reason"] == "нет данных" for row in quiet["skipped"])
    crisis = [-0.03, -0.09, -0.04, -0.11, -0.05, -0.08, -0.06, -0.10] * 3
    put_series("IMOEX", crisis)
    loud = generate_maneuvers(user_id="u-reg", mode="paper")
    found = next(item for item in loud["items"] if item["kind"] == "regime")
    assert found["orders"][0]["side"] == "sell"
    assert found["logic_values"]["label"] in {"crisis", "trend_down", "volatility"}


def test_deposit_allocates_without_sales(monkeypatch) -> None:
    _licensed(monkeypatch)
    _profile("u-dep", max_position_pct="1")
    _trade("u-dep", "SBER", "10", "1000", "sber")
    ensure_account(account_id="p-u-dep", user_id="u-dep", venue="act", mode="paper")
    record_transaction(
        account_id="p-u-dep",
        user_id="u-dep",
        mode="paper",
        venue="act",
        external_id="dep",
        kind="deposit",
        instrument_id="CASH",
        ticker="CASH",
        qty="0",
        amount="2000",
        ccy="RUB",
        event_time=datetime(2024, 6, 1, tzinfo=timezone.utc),
    )
    batch = generate_maneuvers(user_id="u-dep", mode="paper")
    found = next(item for item in batch["items"] if item["kind"] == "deposit")
    assert found["orders"]
    assert all(order["side"] == "buy" for order in found["orders"])
    assert found["orders"][0]["ticker"] == "SBER"
    assert found["orders"][0]["qty"] == "10"


def test_user_text_has_no_advice_and_live_stays_off() -> None:
    _profile("u-words", max_position_pct="0.20")
    _trade("u-words", "SBER", "80", "8000", "sber")
    _trade("u-words", "GAZP", "20", "2000", "gazp", when=datetime(2024, 1, 3, tzinfo=timezone.utc))
    batch = propose(user_id="u-words")
    blob = json.dumps(batch, ensure_ascii=False, default=str).lower()
    for phrase in FORBIDDEN:
        assert phrase not in blob
    live = generate_maneuvers(user_id="u-words", mode="live")
    assert live["items"] == []
    set_global("qa_act_live", False)


def test_generator_flag_off_uses_previous_proposer() -> None:
    set_global("qa_maneuver_generator", False)
    _profile("u-off", max_position_pct="0.20")
    _trade("u-off", "SBER", "80", "8000", "sber")
    _trade("u-off", "GAZP", "20", "2000", "gazp", when=datetime(2024, 1, 3, tzinfo=timezone.utc))
    batch = propose(user_id="u-off")
    assert any(item["kind"] == "reduce_weight" for item in batch["items"])
