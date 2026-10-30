"""PIT layer: knowledge_time ≠ event_time, free-source panel, no look-ahead."""
from __future__ import annotations

from pathlib import Path

from app.services.pit.clock import Observation, as_day, infer_knowledge_time, latest_visible, observation, reject_future_as_of
from app.services.pit.cross_asset import build_risk_book
from app.services.pit.edgar import extract_risk_factors, hashed_embedding, latest_fact_as_of
from app.services.pit.fundamentals import style_scores
from app.services.pit.macro_panel import cftc_observation, panel_as_of
from app.services.pit.news_events import article_observation, classify_event, taxonomy_features
from app.services.pit.short_interest import squeeze_features
from app.services.pit.slippage import implementation_shortfall_bps, model_from_fills, predicted_cost_bps
from app.services.pit.store import build_session, load_session, persist_session, replay_sessions
from app.services.pit.universe import construct_universe, is_listed_as_of


def test_clock_hides_unreleased_vintage():
    payems = observation("PAYEMS", 150_000.0, event_time="2024-01-31")
    # January payrolls are not knowable on January 31 (lag 12d).
    assert payems.event_time == "2024-01-31"
    assert payems.knowledge_time == "2024-02-12"
    assert payems.known_at("2024-02-05") is False
    assert latest_visible([payems], "2024-02-05") is None
    assert latest_visible([payems], "2024-02-12") is payems


def test_clock_prefers_filed_over_lag():
    row = observation("EDGAR_10K", 1.0, event_time="2023-12-31", released="2024-02-20")
    assert row.knowledge_time == "2024-02-20"
    assert row.known_at("2024-02-19") is False
    assert row.known_at("2024-02-20") is True


def test_reject_future_as_of():
    assert reject_future_as_of("2099-01-01", today="2026-09-21") == ""
    assert reject_future_as_of("2026-09-21", today="2026-09-21") == "2026-09-21"


def test_universe_drops_delisted_and_illiquid():
    as_of = "2026-09-21"
    names = construct_universe(
        [
            {"symbol": "DEAD", "last_bar_date": "2024-01-02", "adv_usd": 50_000_000},
            {"symbol": "THIN", "last_bar_date": "2026-09-21", "adv_usd": 100},
            {"symbol": "GONE", "last_bar_date": "2026-09-20", "listing_end": "2026-09-01", "adv_usd": 5_000_000},
            {"symbol": "AAPL", "last_bar_date": "2026-09-20", "adv_usd": 2_000_000_000},
        ],
        as_of=as_of,
    )
    assert names == ["AAPL"]
    assert is_listed_as_of(last_bar_date="2026-09-22", as_of=as_of) is False


def test_macro_panel_does_not_use_unreleased_print(tmp_path: Path, monkeypatch):
    payload = {
        "observations": [
            {"date": "2024-01-31", "value": "3.7", "realtime_start": "2024-02-12"},
            {"date": "2024-02-29", "value": "3.9", "realtime_start": "2024-03-11"},
        ]
    }
    panel = panel_as_of({"UNRATE": payload}, "2024-02-20")
    assert panel["UNRATE"] == 3.7
    later = panel_as_of({"UNRATE": payload}, "2024-03-11")
    assert later["UNRATE"] == 3.9


def test_cftc_uses_publication_lag():
    row = cftc_observation("ES", "2024-06-04", 0.12)
    assert row.known_at("2024-06-04") is False
    assert row.known_at("2024-06-08") is True


def test_cross_asset_book_has_sleeves():
    hist = {
        "SPY": [0.01, -0.01, 0.02, 0.00, 0.01],
        "TLT": [-0.005, 0.004, -0.003, 0.002, -0.001],
        "VIX": [0.04, -0.03, 0.05, -0.02, 0.01],
    }
    book = build_risk_book(hist, as_of="2026-09-21")
    assert book["sleeves"]["SPY"] == "equity"
    assert "TLT" in book["sleeves"]
    assert book["beta_to_spy"]["SPY"] == 1.0


def test_news_taxonomy_and_lookahead_drop():
    assert classify_event("Acme beats estimates, raises guidance") == "earnings"
    assert classify_event("DoJ files lawsuit against Acme") == "litigation"
    early = article_observation(title="Merger talks", published_at="2026-09-22", polarity=0.2)
    late = article_observation(title="Quarterly results", published_at="2026-09-20", polarity=-0.1)
    feats = taxonomy_features([early, late], as_of="2026-09-21")
    assert feats["earnings"] == 1.0
    assert feats["m_and_a"] == 0.0
    assert feats["n"] == 1.0


def test_style_scores_from_extras_not_raw_dump():
    extras = {
        "fmp_roe": 0.25,
        "fmp_roa": 0.12,
        "fmp_margin": 0.2,
        "fmp_pe_inv": 0.05,
        "fmp_de": 0.4,
        "fund_present": 1.0,
    }
    scores = style_scores(extras)
    assert scores["present"] == 1.0
    assert scores["quality"] > 0
    assert scores["value"] > 0
    assert scores["leverage"] > 0
    assert style_scores({})["present"] == 0.0


def test_edgar_risk_factors_embedding_and_filed_vintage():
    text = "ITEM 1. BUSINESS\nfoo\nITEM 1A. RISK FACTORS\nlitigation climate supply\nITEM 1B. UNRESOLVED\nbar"
    chunk = extract_risk_factors(text)
    assert "litigation" in chunk.lower()
    assert "UNRESOLVED" not in chunk
    vec = hashed_embedding(chunk)
    assert len(vec) == 32
    assert abs(sum(x * x for x in vec) - 1.0) < 1e-3
    rows = [
        {"end": "2023-12-31", "filed": "2024-02-20", "val": 10},
        {"end": "2024-12-31", "filed": "2025-02-18", "val": 12},
    ]
    assert latest_fact_as_of(rows, "2024-06-01") == 10.0
    assert latest_fact_as_of(rows, "2024-02-19") is None
    assert latest_fact_as_of(rows, "2025-02-18") == 12.0


def test_finra_squeeze_ignores_unreleased_settlement():
    history = [
        {
            "settlement_date": "2026-08-31",
            "published_at": "2026-09-08",
            "current_short_position": 1_000_000,
            "days_to_cover": 2.0,
        },
        {
            "settlement_date": "2026-09-15",
            "published_at": "2026-09-23",
            "current_short_position": 1_500_000,
            "days_to_cover": 6.0,
        },
    ]
    early = squeeze_features(history, as_of="2026-09-10", symbol="AAPL")
    assert early["present"] == 1.0
    assert early["si_level"] == 1_000_000
    late = squeeze_features(history, as_of="2026-09-23", symbol="AAPL")
    assert late["si_level"] == 1_500_000
    assert late["si_chg"] > 0
    assert late["crowding"] > early["crowding"]


def test_slippage_from_own_fills_not_spectral():
    buy = implementation_shortfall_bps(100.0, 100.10, "buy")
    sell = implementation_shortfall_bps(100.0, 99.90, "sell")
    assert buy == 10.0
    assert sell == 10.0
    model = model_from_fills(
        [
            {"signal_generated_price": 50.0, "fill_price": 50.05, "direction": "long"},
            {"signal_generated_price": 50.0, "fill_price": 50.02, "direction": "long"},
        ]
        * 5
    )
    assert model["n"] == 10
    assert model["mean_bps"] > 0
    assert predicted_cost_bps("AAPL", model, conservative=False) == model["mean_bps"]
    assert predicted_cost_bps("AAPL", model) == model["p90_bps"]
    assert predicted_cost_bps("AAPL", {"n": 1, "mean_bps": 99}) < 20


def test_session_replay_skips_future(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("app.services.pit.store._root", lambda: tmp_path)
    persist_session(
        build_session(
            as_of="2026-09-20",
            universe=["AAPL"],
            macro={"VIXCLS": 15.0},
        )
    )
    persist_session(build_session(as_of="2026-09-22", universe=["MSFT"]))
    days = replay_sessions(through="2026-09-21", today="2026-09-21")
    assert [as_day(d["event_time"]) for d in days] == ["2026-09-20"]
    assert load_session("2026-09-22", today="2026-09-21") is None


def test_stooq_universe_no_survivorship_from_today_edgar():
    from app.services.pit.universe import member_from_bars, universe_from_stooq_members

    dead_bars = [
        {"date": "2020-01-02", "close": 10.0, "volume": 2_000_000},
        {"date": "2020-01-03", "close": 10.0, "volume": 2_000_000},
    ]
    live_bars = [{"date": f"2026-09-{d:02d}", "close": 100.0, "volume": 50_000} for d in range(10, 21)]
    members = [
        member_from_bars("DEAD", dead_bars, as_of="2026-09-21"),
        member_from_bars("AAPL", live_bars, as_of="2026-09-21"),
        member_from_bars("MSFT", live_bars, as_of="2026-09-21"),
    ]
    members = [m for m in members if m]
    today_u = universe_from_stooq_members(
        members,
        as_of="2026-09-21",
        edgar_tickers={"AAPL"},
        today="2026-09-21",
        min_adv_usd=1_000.0,
    )
    assert today_u == ["AAPL"]
    # Today's EDGAR file must not rewrite a past research date.
    asof_not_today = universe_from_stooq_members(
        members,
        as_of="2026-09-21",
        edgar_tickers={"AAPL"},
        today="2026-09-22",
        min_adv_usd=1_000.0,
    )
    assert set(asof_not_today) == {"AAPL", "MSFT"}
    assert "DEAD" not in asof_not_today


def test_fundamentals_statements_ignore_unfiled():
    from app.services.pit.fundamentals import extras_from_statements

    rows = [
        {
            "fillingDate": "2024-02-01",
            "netIncome": 10.0,
            "equity": 100.0,
            "revenue": 50.0,
            "assets": 200.0,
            "debt": 20.0,
        },
        {
            "fillingDate": "2025-02-01",
            "netIncome": 99.0,
            "equity": 100.0,
            "revenue": 50.0,
            "assets": 200.0,
            "debt": 20.0,
        },
    ]
    early = extras_from_statements(rows, as_of="2024-06-01")
    assert early["fmp_roe"] == 0.1
    late = extras_from_statements(rows, as_of="2025-02-01")
    assert late["fmp_roe"] == 0.99


def test_cross_asset_drops_future_bars():
    from app.services.pit.cross_asset import book_from_bars, returns_as_of

    bars = [
        {"date": "2026-09-18", "close": 100.0},
        {"date": "2026-09-19", "close": 101.0},
        {"date": "2026-09-22", "close": 200.0},
    ]
    rets = returns_as_of(bars, as_of="2026-09-21")
    assert len(rets) == 1
    assert abs(rets[0] - 0.01) < 1e-9
    book = book_from_bars({"SPY": bars, "TLT": bars}, as_of="2026-09-21")
    assert book["sleeves"] == {}  # need ≥3 returns


def test_risk_factor_embedding_reports_engine():
    from app.services.pit.edgar import risk_factor_embedding

    vec, engine = risk_factor_embedding("ITEM 1A. RISK FACTORS\nlitigation climate supply chain")
    assert engine in {"hash", "finbert"}
    assert vec
    assert abs(sum(x * x for x in vec) - 1.0) < 1e-2


def test_fred_http_keeps_realtime_start():
    from app.services.pit.macro_panel import panel_as_of

    payload = {
        "observations": [
            {"date": "2024-01-31", "value": "3.7", "realtime_start": "2024-02-02", "realtime_end": "2024-03-07"},
            {"date": "2024-01-31", "value": "3.8", "realtime_start": "2024-03-08", "realtime_end": "9999-12-31"},
        ]
    }
    # First print 3.7; revision 3.8 only after 2024-03-08.
    assert panel_as_of({"UNRATE": payload}, "2024-02-20")["UNRATE"] == 3.7
    assert panel_as_of({"UNRATE": payload}, "2024-03-08")["UNRATE"] == 3.8

