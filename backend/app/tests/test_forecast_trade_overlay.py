from __future__ import annotations

from types import SimpleNamespace

from app.services.forecast.cost_model import round_trip_cost_return
from app.services.forecast.excess_labels import excess_direction_labels
from app.services.forecast.pit_snapshots import persist_pit_snapshot
from app.services.forecast.trade_overlay import (
    conformal_blocks_direction,
    shrink_probability,
    size_mult_from_p,
)


def test_shrink_is_identity_until_enough_samples():
    assert shrink_probability(0.8, observed_acc=0.4, n=5) == 0.8
    mixed = shrink_probability(0.8, observed_acc=0.4, n=40)
    assert 0.4 < mixed < 0.8


def test_size_mult_never_above_one_and_respects_side():
    assert size_mult_from_p(0.9, direction="long") == 1.0
    assert size_mult_from_p(0.4, direction="long") == 0.0
    assert size_mult_from_p(0.9, direction="short") == 0.0
    assert size_mult_from_p(0.1, direction="short") == 1.0


def test_conformal_blocks_only_with_enough_data():
    weak = SimpleNamespace(sufficient_data=False, lower_70=-0.1, upper_70=-0.01)
    assert conformal_blocks_direction("long", weak) is False
    against = SimpleNamespace(sufficient_data=True, lower_70=-0.08, upper_70=-0.01)
    assert conformal_blocks_direction("long", against) is True
    ok = SimpleNamespace(sufficient_data=True, lower_70=-0.02, upper_70=0.04)
    assert conformal_blocks_direction("long", ok) is False


def test_cost_flips_tiny_excess_to_loss():
    asset = [100.0, 100.0, 100.06]
    bench = [100.0, 100.0, 100.0]
    raw = excess_direction_labels(asset, bench, horizon=2, cost_return=0.0)
    costly = excess_direction_labels(asset, bench, horizon=2, cost_return=0.01)
    assert raw[0] == 1
    assert costly[0] == -1
    assert round_trip_cost_return("AAPL") == 4.0 / 10_000.0


def test_pit_snapshot_writes_dated_file(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.forecast.pit_snapshots.settings.PIT_STORE_DIR",
        str(tmp_path),
        raising=False,
    )
    path = persist_pit_snapshot("AAPL", {"fmp_roe": 0.2, "fund_present": 1.0})
    assert path is not None
    assert path.is_file()
    assert "fmp_roe" in path.read_text(encoding="utf-8")
