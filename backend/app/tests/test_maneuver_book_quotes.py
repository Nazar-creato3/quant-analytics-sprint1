"""Phase 1: book_gate receives real bid/ask from Terminal order-book snapshots."""
from __future__ import annotations

from types import SimpleNamespace

from app.services.quant_desk.book_quotes import quotes_for_desk, top_of_book
from app.services.quant_desk.overlays import desk_overlay


def _lvl(price: float, size: float = 10.0) -> SimpleNamespace:
    return SimpleNamespace(price=price, size=size)


def test_top_of_book_uses_best_bid_ask_not_first_row():
    snap = SimpleNamespace(
        bids=[_lvl(99.0, 5), _lvl(100.0, 8)],
        asks=[_lvl(101.0, 3), _lvl(100.2, 4)],
        source="binance_depth",
    )
    q = top_of_book(snap)
    assert q["have_quoted_spread"] is True
    assert q["bid"] == 100.0
    assert q["ask"] == 100.2
    assert q["bid_sz"] == 8.0
    assert q["ask_sz"] == 4.0


def test_top_of_book_empty_when_no_ladder():
    assert top_of_book(None) == {}
    assert top_of_book(SimpleNamespace(bids=[], asks=[], source="no_data")) == {}


def test_zero_size_yahoo_nbbo_still_passes_prices():
    snap = SimpleNamespace(
        bids=[_lvl(50.0, 0.0)],
        asks=[_lvl(50.05, 0.0)],
        source="yfinance_nbbo_thin",
    )
    q = top_of_book(snap)
    assert q["bid"] == 50.0
    assert q["ask"] == 50.05
    assert q["bid_sz"] is None
    assert q["ask_sz"] is None


def test_desk_overlay_changes_size_when_quotes_vs_atr_only():
    common = dict(
        equity_usd=100_000,
        price=100.0,
        atr=2.0,
        current_usd=8_000,
        direction="long",
        realized_ann_vol=0.2,
        atr_pct=0.08,
        macro_tilt=0.0,
    )
    atr_only = desk_overlay(**common)
    tight = desk_overlay(**common, bid=100.0, ask=100.04, bid_sz=20, ask_sz=20)
    wide = desk_overlay(**common, bid=100.0, ask=101.0, bid_sz=20, ask_sz=20)

    assert atr_only.allow is True
    assert tight.allow is True
    assert tight.size_mult != atr_only.size_mult or tight.reasons != atr_only.reasons
    assert wide.allow is False
    desk_q = quotes_for_desk({"bid": 100.0, "ask": 100.04, "bid_sz": 20, "ask_sz": 20})
    assert desk_q["bid"] == 100.0 and desk_q["ask"] == 100.04


def test_reapply_desk_size_mult_survives_allocate_overwrite():
    from app.services.risk.maneuver_generator import ManeuverGenerator, ManeuverOutput

    gen = ManeuverGenerator(portfolio_size=10_000)
    m = ManeuverOutput(
        rank=1,
        ticker="AAPL",
        strategy_type="momentum",
        direction="long",
        entry_zone_low=100,
        entry_zone_high=101,
        exit_zone_low=110,
        exit_zone_high=111,
        stop_loss=95,
        take_profit=110,
        invalidation_level=94,
        risk_percent=10.0,
        position_size_usd=1000.0,
        expected_return_low=1,
        expected_return_high=2,
        expected_pnl_low=10,
        expected_pnl_high=20,
        confidence=0.7,
        time_horizon="1–5 days",
        catalyst="—",
        rationale="t",
        execution_plan="x Размер: $1,000.",
        signal_meta={"desk_overlay": {"size_mult": 0.7, "have_quoted_spread": True}},
    )
    out = gen._reapply_desk_size_mult([m])
    assert out[0].position_size_usd == 700.0
    assert out[0].signal_meta["desk_overlay"]["applied_after_allocate"] is True
