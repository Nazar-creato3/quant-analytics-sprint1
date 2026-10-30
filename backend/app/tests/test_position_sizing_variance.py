"""Position sizing variance across maneuvers."""
from __future__ import annotations

from app.services.risk.position_sizing import conviction_risk_pct


def test_conviction_risk_spreads_with_confidence():
    low = conviction_risk_pct(
        base_max_risk_pct=2.0,
        confidence=0.45,
        atr_pct=0.025,
        volume_z=-0.5,
    )
    high = conviction_risk_pct(
        base_max_risk_pct=2.0,
        confidence=0.88,
        atr_pct=0.012,
        volume_z=1.0,
    )
    assert high > low
    assert low >= 0.12
    assert high <= 2.0


def test_varied_notionals_under_same_cap():
    sizes = []
    for conf, atr in ((0.5, 0.03), (0.75, 0.015), (0.62, 0.022)):
        risk = conviction_risk_pct(
            base_max_risk_pct=2.0,
            confidence=conf,
            atr_pct=atr,
        )
        portfolio = 10_800.0
        entry = 100.0
        stop = entry - entry * atr * 2
        risk_amt = portfolio * (risk / 100)
        notional = (risk_amt / (entry - stop)) * entry
        sizes.append(round(notional, 2))
    assert len(set(sizes)) >= 2
    assert max(sizes) > min(sizes) * 1.15
