"""Phases 2–4: BotRiskGuard, ensemble shadow (no live switch), regime/BOCPD."""
from __future__ import annotations

from types import SimpleNamespace

from app.services.bot_risk.guard import BotRiskGuard, BotRiskConfig
from app.services.bot_risk.portfolio import build_bot_refs, build_portfolio_snapshot
from app.services.bot_risk.types import CorrelationMode
from app.services.risk.ensemble_shadow import compare_row, maybe_override_from_ensemble, side_from_direction
from app.services.risk.maneuver_bot_guard import gate_maneuver
from app.services.risk.maneuver_regime import (
    apply_bocpd_to_confidence,
    regime_blocks_new_risk,
    regime_size_mult,
)
from app.tests.test_bot_risk_module import _dca_bot


def test_bot_risk_blocks_maneuver_on_same_instrument_as_bot():
    guard = BotRiskGuard(
        BotRiskConfig(
            risk_per_trade_pct=1.5,
            circuit_breaker_drawdown_pct=10.0,
            correlation_mode=CorrelationMode.BLOCK,
            default_stop_loss_pct=0.05,
            max_position_pct=10.0,
        )
    )
    refs = build_bot_refs(dca={"dca-1": _dca_bot("dca-1", "BTC/USDT", with_position=True)})
    snap = build_portfolio_snapshot(refs)
    ok, _ = gate_maneuver("ETHUSDT", snapshot=snap, selected=(), guard=guard)
    blocked, reason = gate_maneuver("BTCUSDT", snapshot=snap, selected=(), guard=guard)
    assert ok is True
    assert blocked is False
    assert "BTC" in reason or "dca-1" in reason


def test_bot_risk_blocks_second_maneuver_same_underlying():
    guard = BotRiskGuard(
        BotRiskConfig(
            risk_per_trade_pct=1.5,
            circuit_breaker_drawdown_pct=10.0,
            correlation_mode=CorrelationMode.BLOCK,
            default_stop_loss_pct=0.05,
            max_position_pct=10.0,
        )
    )
    first = SimpleNamespace(ticker="AAPL", risk=SimpleNamespace(position_size_usd=500, position_size_shares=3))
    allowed, _ = gate_maneuver("MSFT", snapshot=None, selected=[first], guard=guard)
    blocked, _ = gate_maneuver("AAPL", snapshot=None, selected=[first], guard=guard)
    assert allowed is True
    assert blocked is False


def test_circuit_breaker_blocks_new_maneuver_without_halting_bots():
    guard = BotRiskGuard(
        BotRiskConfig(
            risk_per_trade_pct=1.5,
            circuit_breaker_drawdown_pct=5.0,
            correlation_mode=CorrelationMode.BLOCK,
            default_stop_loss_pct=0.05,
            max_position_pct=10.0,
        )
    )
    dca = _dca_bot("dca-1", "BTC/USDT", total_pnl=-600.0)
    refs = build_bot_refs(dca={"dca-1": dca})
    snap = build_portfolio_snapshot(refs, peak_pnl=0.0)
    allowed, reason = gate_maneuver("MSFT", snapshot=snap, selected=(), guard=guard)
    assert allowed is False
    assert "drawdown" in reason.lower() or "circuit" in reason.lower()
    assert dca.get("is_paused") is not True
    assert dca.get("risk_halt") is not True


def test_ensemble_shadow_compare_does_not_switch_default():
    fc = SimpleNamespace(direction_consensus=-1, models_agreeing=3, models_total=5)
    row = compare_row(
        ticker="AAPL",
        clf_direction="long",
        clf_confidence=0.7,
        forecast=fc,
    )
    assert row["disagree"] is True
    assert row["used_for_maneuver"] is False
    assert side_from_direction("long") == 1
    # Live switch stays off unless settings say ensemble (tested separately).
    d, c = maybe_override_from_ensemble(direction="long", confidence=0.7, forecast=fc)
    assert d == "long"
    assert c == 0.7


def test_ensemble_flag_can_override_when_explicit(monkeypatch):
    from app.core import config as cfg
    from app.services.risk import ensemble_shadow as es

    monkeypatch.setattr(cfg.settings, "MANEUVER_SIGNAL_SOURCE", "ensemble")
    monkeypatch.setattr(es.settings, "MANEUVER_SIGNAL_SOURCE", "ensemble")
    fc = SimpleNamespace(direction_consensus=-1, models_agreeing=4, models_total=5)
    d, c = es.maybe_override_from_ensemble(direction="long", confidence=0.7, forecast=fc)
    assert d == "short"
    assert abs(c - 0.8) < 1e-9


def test_regime_size_and_block():
    assert regime_size_mult({"size_mult": 0.6}) == 0.6
    assert regime_blocks_new_risk({"alpha_on": False, "size_mult": 0.0}) is True
    assert regime_blocks_new_risk({"alpha_on": True, "size_mult": 1.0}) is False
    assert regime_blocks_new_risk({}) is False


def test_bocpd_cuts_confidence_on_break_vs_calm():
    import numpy as np

    rng = np.random.default_rng(0)
    calm = np.cumsum(np.concatenate([[100.0], rng.normal(0.02, 0.15, 80)]))
    shock = np.concatenate([
        np.cumsum(np.concatenate([[100.0], rng.normal(0.02, 0.12, 50)])),
        np.cumsum(np.concatenate([[calm[0]], rng.normal(-1.2, 3.5, 40)])),
    ])
    c_calm, m_calm = apply_bocpd_to_confidence(0.80, [float(x) for x in calm], hmm_label="bull")
    c_shock, m_shock = apply_bocpd_to_confidence(0.80, [float(x) for x in shock], hmm_label="volatile")
    assert m_shock.get("changepoint_probability", 0) >= 0
    assert c_shock <= c_calm + 1e-9
    if m_shock.get("confidence_scaled"):
        assert c_shock < 0.80
    assert "changepoint_probability" in m_shock or len(shock) < 22
