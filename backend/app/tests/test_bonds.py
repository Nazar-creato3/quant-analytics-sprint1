"""Bond yield/duration/G-spread/stress (prompt 56, R5)."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.services.bonds import store
from app.services.bonds.analytics import (
    convexity,
    current_yield,
    g_spread,
    macaulay_duration,
    metrics_from_flows,
    modified_duration,
    rate_stress,
    year_fraction,
    yield_to_maturity,
)
from app.services.bonds.ingest import discrepancy_kop, merge_cashflows
from app.services.bonds.service import bond_card, ensure_fixtures, portfolio_bond_stress, portfolio_bonds
from app.services.legal.catalog import load_ui_texts, reset_cache
from app.services.qa.feature_flags import reset_for_tests, set_global
from app.tests.qa_session import bind_session_user, clear_session_user

FIX = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "bonds" / "universe.json"


def setup_function() -> None:
    reset_for_tests()
    set_global("qa_bonds", True)
    store.reset()
    ensure_fixtures()


def teardown_function() -> None:
    store.reset()
    reset_for_tests()
    clear_session_user()


def _hand_ytm(cfs: list[float], times: list[float], price: float) -> float:
    y = 0.08
    for _ in range(80):
        px = sum(c / (1 + y) ** t for c, t in zip(cfs, times))
        dpx = sum(-t * c / (1 + y) ** (t + 1) for c, t in zip(cfs, times))
        y -= (px - price) / dpx
    return y


def _ofz_flows() -> tuple[list[float], list[float], float]:
    uni = json.loads(FIX.read_text(encoding="utf-8"))
    ofz = next(r for r in uni["references"] if r["figi"] == "OFZ26238")
    settle = date.fromisoformat(uni["settlement"])
    times = [year_fraction(settle, date.fromisoformat(r["on_date"])) for r in ofz["cashflows"]]
    cfs = [float(r["amount_per_bond"]) for r in ofz["cashflows"]]
    return cfs, times, float(ofz["dirty_price"])


def test_ofz_pd_ytm_and_duration_within_tol() -> None:
    cfs, times, px = _ofz_flows()
    expected_y = _hand_ytm(cfs, times, px)
    y = yield_to_maturity(cfs, times, px)
    assert y is not None
    assert abs(y - expected_y) < 1e-10
    assert abs(y * 10_000 - expected_y * 10_000) <= 1.0  # 1 bp
    mac = macaulay_duration(cfs, times, y, px)
    hand_mac = sum(t * c / (1 + y) ** t for c, t in zip(cfs, times)) / px
    assert mac is not None
    assert abs(mac - hand_mac) <= 0.01


def test_corp_amort_offer_and_floater() -> None:
    uni = json.loads(FIX.read_text(encoding="utf-8"))
    settle = date.fromisoformat(uni["settlement"])
    corp = next(r for r in uni["references"] if r["figi"] == "CORPAMORT")
    dates = [date.fromisoformat(r["on_date"]) for r in corp["cashflows"]]
    amts = [float(r["amount_per_bond"]) for r in corp["cashflows"]]
    m = metrics_from_flows(
        settlement=settle,
        flow_dates=dates,
        amounts=amts,
        dirty_price=float(corp["dirty_price"]),
        clean_price=float(corp["clean_price"]),
        aci=float(corp["aci"]),
        annual_coupon=float(corp["annual_coupon"]),
        curve_points=[(1.0, 0.07), (3.0, 0.075), (5.0, 0.08)],
    )
    assert m["status"] == "ok"
    offer = metrics_from_flows(
        settlement=settle,
        flow_dates=[date.fromisoformat(r["on_date"]) for r in corp["cashflows_to_offer"]],
        amounts=[float(r["amount_per_bond"]) for r in corp["cashflows_to_offer"]],
        dirty_price=float(corp["dirty_price"]),
        clean_price=float(corp["clean_price"]),
        aci=5.0,
        annual_coupon=90.0,
        to_offer=True,
    )
    assert offer["ytp"] is not None
    flt = next(r for r in uni["references"] if r["figi"] == "FLOAT1")
    fm = metrics_from_flows(
        settlement=settle,
        flow_dates=[date.fromisoformat(r["on_date"]) for r in flt["cashflows"]],
        amounts=[float(r["amount_per_bond"]) for r in flt["cashflows"]],
        dirty_price=float(flt["dirty_price"]),
        clean_price=float(flt["clean_price"]),
        aci=2.0,
        annual_coupon=165.0,
        floater=True,
        next_reset=date.fromisoformat(flt["next_reset"]),
    )
    assert abs(fm["macaulay"] - year_fraction(settle, date.fromisoformat(flt["next_reset"]))) < 1e-9


def test_g_spread_and_stress_formula() -> None:
    ytm = 0.12
    mac = 3.0
    gs = g_spread(ytm, mac, [(1.0, 0.07), (3.0, 0.075), (5.0, 0.08)])
    assert gs is not None
    assert abs(gs - 0.045) < 1e-12
    d_mod = modified_duration(mac, ytm)
    conv = 20.0
    p = 10_000.0
    dy = 0.02
    assert abs(rate_stress(dirty_value=p, d_mod=d_mod, conv=conv, shift_yield=dy) - (-d_mod * dy * p + 0.5 * conv * dy * dy * p)) < 1e-9


def test_current_yield_and_no_zero_fill() -> None:
    assert current_yield(70, 1000) == 0.07
    assert yield_to_maturity([], [], 0) is None
    card = bond_card("MISSING")
    assert card["status"] == "нет данных"


def test_tinvest_wins_and_quality_log() -> None:
    merge_cashflows(
        "X",
        [{"on_date": "2027-01-01", "amount_per_bond": 35.0}],
        [{"on_date": "2027-01-01", "amount_per_bond": 35.02}],
    )
    assert discrepancy_kop(35.0, 35.02)
    assert store.get_events("X")[0]["source"] == "tinvest"
    assert store.quality_log()


def test_portfolio_and_http() -> None:
    bind_session_user("u-56")
    book = portfolio_bonds("u-56", "paper")
    assert book["data_status"] == "нет данных"
    assert book["issues"] == []
    assert book["summary"]["nav_rub"] is None
    stress = portfolio_bond_stress("u-56", "paper", shift_bp=200)
    assert stress["elapsed_ms"] < 1000
    assert stress["delta_rub"] is None
    client = TestClient(app)
    r = client.get("/api/v1/portfolio/paper/bonds")
    assert r.status_code == 200
    s = client.get("/api/v1/portfolio/paper/bonds/stress", params={"shift_bp": 100})
    assert s.status_code == 200
    c = client.get("/api/v1/bonds/OFZ26238")
    assert c.status_code == 200
    set_global("qa_bonds", False)
    assert client.get("/api/v1/portfolio/paper/bonds").status_code == 404


def test_ui_texts_bonds() -> None:
    reset_cache()
    bonds = load_ui_texts()["bonds"]
    blob = " ".join(str(v).lower() for v in bonds.values())
    assert "стоит купить" not in blob
    assert "выгодно" not in blob
    assert bonds["g_spread"].startswith("Премия")


def test_convexity_positive_for_fixed() -> None:
    cfs, times, px = _ofz_flows()
    y = yield_to_maturity(cfs, times, px) or 0
    cnv = convexity(cfs, times, y, px)
    assert cnv is not None and cnv > 0


def test_ytm_returns_none_when_newton_does_not_converge(monkeypatch) -> None:
    """AUD-F-02: an unfinished Newton step is not a yield."""
    from app.services.bonds import analytics as bond_math
    from app.services.bonds.analytics import price_from_yield

    monkeypatch.setattr(bond_math, "YTM_ITERS", 1)
    cfs = [5.0, 105.0]
    times = [1.0, 2.0]
    px = price_from_yield(cfs, times, 0.05)
    assert yield_to_maturity(cfs, times, px, guess=5.0) is None


def test_bond_payload_hides_vendor_and_flow_keys() -> None:
    """AUD-F-04: the card the UI renders has no vendor or snake_case flow type."""
    card = bond_card("OFZ26238")
    blob = json.dumps(card, ensure_ascii=False).lower()
    assert "tinvest" not in blob
    assert "quantlib" not in blob
    assert "numpy" not in blob
    assert card["source"] == "данные брокера"
    assert card["cashflows"]
    assert all(cf.get("type_label") and "type" not in cf for cf in card["cashflows"])
    book = portfolio_bonds("u-56", "paper")
    book_blob = json.dumps(book, ensure_ascii=False).lower()
    assert book["source"] == "данные брокера"
    assert "tinvest" not in book_blob
    assert "_flows" not in book_blob
