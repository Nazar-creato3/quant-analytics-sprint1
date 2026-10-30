"""Prompt 36: methods, constraints, costs, tax base, properties. Does not import app.main."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import numpy as np

from app.services.act_desk.service import propose, reset as reset_act, save_profile
from app.services.explanations.service import filter_wording
from app.services.portfolio_book.store import get_book
from app.services.qa.feature_flags import is_enabled, reset_for_tests
from app.services.target_portfolio.optimize import solve_erc, solve_mean_variance
from app.services.target_portfolio.service import build_for_user, construct
from app.services.target_portfolio.tax import dividend_ndfl, fifo_realize, tax_base_for_year
from app.services.target_portfolio.types import ConstraintSet, ForecastView, Instrument, TaxLot
from app.services.target_portfolio.views import view_from_forecast

REPO = Path(__file__).resolve().parents[3]
FORBIDDEN = ("рекомендуем", "советуем", "подходит вам", "соответствует вашему профилю", "купите", "продайте")
LOOSE = ConstraintSet(name_cap=Decimal("1"), allow_shorts=False)
COST = {"brokers": {"paper": {"tariffs": {"sim": {"commission_rate": "0.0001"}}}}}


def _inst(
    ticker: str,
    returns: tuple[float, ...] = (),
    *,
    mu: float | None = None,
    price: str = "10",
    license_tag: str = "display_allowed",
    display: bool = True,
    sector: str = "A",
    issuer: str = "",
    adv: str | None = None,
    spread: str = "0",
    slip: str = "0",
    lot: str = "1",
) -> Instrument:
    return Instrument(
        ticker=ticker,
        price=Decimal(price),
        license_tag=license_tag,
        display_allowed=display,
        lot_size=Decimal(lot),
        price_step=Decimal("0.01"),
        sector=sector,
        issuer=issuer or ticker,
        adv=None if adv is None else Decimal(adv),
        spread_bps=Decimal(spread),
        slippage_bps=Decimal(slip),
        mu=mu,
        returns=returns,
    )


def _panel(n: int, seed: int, vol: float = 0.01) -> tuple[float, ...]:
    rng = np.random.default_rng(seed)
    return tuple(float(x) for x in rng.normal(0.0, vol, n))


def test_equal_weight_matches_independent_sum():
    names = [_inst("AAA"), _inst("BBB"), _inst("CCC"), _inst("DDD")]
    book = construct(names, method="equal_weight", capital=Decimal("1000"), constraints=LOOSE)
    assert book["status"] == "ok"
    assert book["target_source"] == "user"

    def reference(n: int) -> list[float]:
        total = 0
        raw = []
        for _ in range(n):
            raw.append(1)
            total += 1
        return [item / total for item in raw]

    ref = reference(4)
    for weight, expected in zip(book["weights"].values(), ref):
        assert Decimal(weight) == Decimal("0.25")
        assert abs(float(weight) - expected) < 1e-12
    assert Decimal(book["sum_weights"]) == Decimal("1")


def test_weights_ignore_input_order_and_capital_scale():
    series = [_panel(30, 1), _panel(30, 2)]
    small = construct(
        [_inst("AAA", series[0], mu=0.01), _inst("BBB", series[1], mu=0.02)],
        method="equal_weight",
        capital=Decimal("1000"),
        constraints=LOOSE,
    )
    large = construct(
        [_inst("BBB", series[1], mu=0.02), _inst("AAA", series[0], mu=0.01)],
        method="equal_weight",
        capital=Decimal("100000"),
        constraints=LOOSE,
    )
    assert small["weights"] == large["weights"]


def test_no_shorts_and_name_cap():
    series = (_panel(40, 3, 0.02), _panel(40, 4, 0.01), _panel(40, 5, 0.03))
    book = construct(
        [
            _inst("AAA", series[0], mu=0.2),
            _inst("BBB", series[1], mu=-0.2),
            _inst("CCC", series[2], mu=0.05),
        ],
        method="mean_variance",
        capital=Decimal("10000"),
        constraints=ConstraintSet(name_cap=Decimal("0.5"), allow_shorts=False),
        risk_aversion=2.0,
    )
    assert book["status"] == "ok"
    for weight in book["weights"].values():
        value = Decimal(weight)
        assert value >= 0
        assert value <= Decimal("0.5000001")
    assert abs(Decimal(book["sum_weights"]) - 1) < Decimal("0.0000001")


def test_infeasible_caps_have_a_reason():
    book = construct(
        [_inst("AAA"), _inst("BBB"), _inst("CCC")],
        method="equal_weight",
        capital=Decimal("1000"),
        constraints=ConstraintSet(name_cap=Decimal("0.2"), allow_shorts=False),
    )
    assert book["status"] == "infeasible"
    assert book["weights"] is None
    assert "меньше 1" in book["reason"]


def test_singular_and_ill_conditioned_covariance():
    flat = tuple([0.01] * 12)
    singular = construct(
        [_inst("AAA", flat, mu=0.01), _inst("BBB", flat, mu=0.02)],
        method="mean_variance",
        capital=Decimal("5000"),
        constraints=LOOSE,
    )
    assert singular["status"] in {"ok", "infeasible"}
    if singular["status"] == "ok":
        assert abs(Decimal(singular["sum_weights"]) - 1) < Decimal("0.0001")
        assert singular["cov_note"] == "ridge"
    else:
        assert singular["reason"]
    base = np.linspace(-0.02, 0.03, 36)
    ill = construct(
        [
            _inst("AAA", tuple(float(x) for x in base), mu=0.01),
            _inst("BBB", tuple(float(x + 1e-8) for x in base), mu=0.011),
        ],
        method="hrp",
        capital=Decimal("5000"),
        constraints=LOOSE,
    )
    assert ill["status"] == "ok"
    assert all(np.isfinite(float(v)) for v in ill["weights"].values())
    assert abs(Decimal(ill["sum_weights"]) - 1) < Decimal("0.0001")


def test_erc_matches_inverse_vol_on_diagonal():
    cov = np.diag([0.01, 0.04])
    weights, _solver = solve_erc(
        cov,
        upper=np.ones(2),
        allow_shorts=False,
        groups=[],
        w0=np.zeros(2),
        capital=1.0,
        budget=None,
    )
    sigma = np.sqrt(np.diag(cov))
    inv = 1.0 / sigma
    reference = inv / inv.sum()
    assert np.allclose(weights, reference, atol=1e-3)


def test_mean_variance_matches_two_asset_closed_form():
    cov = np.eye(2)
    mu = np.array([0.10, 0.00])
    lam = 2.0
    weights, _solver = solve_mean_variance(
        cov,
        mu,
        risk_aversion=lam,
        upper=np.ones(2),
        allow_shorts=False,
        groups=[],
        w0=np.zeros(2),
        capital=1.0,
        budget=None,
    )
    # w = (m1 - m2 + λ v2) / (λ (v1 + v2)), clipped to [0, 1]
    closed = (0.10 - 0.0 + lam * 1.0) / (lam * (1.0 + 1.0))
    closed = min(1.0, max(0.0, closed))
    assert abs(float(weights[0]) - closed) < 1e-3
    assert abs(float(weights.sum()) - 1.0) < 1e-6


def test_black_litterman_without_views_is_no_data():
    series = (_panel(20, 7), _panel(20, 8))
    book = construct(
        [_inst("AAA", series[0]), _inst("BBB", series[1])],
        method="black_litterman",
        capital=Decimal("1000"),
        constraints=LOOSE,
        views=[],
    )
    assert book["status"] == "нет данных"
    assert book["weights"] is None
    assert view_from_forecast({"data_status": "нет данных", "ticker": "AAA"}, sigma=0.1) is None
    assert view_from_forecast({"ticker": "AAA", "probability": 0.6}, sigma=0.1) is None


def test_black_litterman_uses_calibrated_probability():
    series = (_panel(30, 9, 0.01), _panel(30, 10, 0.02))
    view = view_from_forecast(
        {"ticker": "AAA", "data_status": "ok", "calibrated_probability": 0.7, "direction": 1},
        sigma=0.01,
    )
    assert view is not None
    book = construct(
        [_inst("AAA", series[0], mu=0.0), _inst("BBB", series[1], mu=0.0)],
        method="black_litterman",
        capital=Decimal("8000"),
        constraints=LOOSE,
        views=[view],
    )
    assert book["status"] == "ok"
    assert Decimal(book["sum_weights"]) == Decimal("1") or abs(Decimal(book["sum_weights"]) - 1) < Decimal("0.0001")


def test_cvar_needs_scenarios_and_respects_long_only():
    empty = construct(
        [_inst("AAA"), _inst("BBB")],
        method="cvar",
        capital=Decimal("1000"),
        constraints=LOOSE,
    )
    assert empty["status"] == "нет данных"
    series = (_panel(48, 11), _panel(48, 12))
    book = construct(
        [_inst("AAA", series[0], mu=0.01), _inst("BBB", series[1], mu=-0.02)],
        method="cvar",
        capital=Decimal("9000"),
        constraints=LOOSE,
    )
    assert book["status"] == "ok"
    assert book["solver"] == "scipy.optimize.linprog.highs"
    for weight in book["weights"].values():
        assert Decimal(weight) >= 0


def test_banned_and_internal_only_are_not_shown():
    book = construct(
        [
            _inst("AAA"),
            _inst("SECRET", license_tag="internal_only", display=False),
            _inst("BAN"),
            Instrument(ticker="NOPRICE", price=None, display_allowed=True, license_tag="display_allowed"),
        ],
        method="equal_weight",
        capital=Decimal("1000"),
        constraints=ConstraintSet(name_cap=Decimal("1"), banned_tickers=("BAN",)),
    )
    assert book["status"] == "ok"
    assert set(book["weights"]) == {"AAA"}
    reasons = {row["ticker"]: row["reason"] for row in book["excluded"]}
    assert "internal_only" in reasons["SECRET"]
    assert "запрещ" in reasons["BAN"]
    assert reasons["NOPRICE"] == "нет цены"


def test_rebalance_not_proposed_when_gain_does_not_cover_costs():
    series = (_panel(24, 13), _panel(24, 14))
    names = [
        _inst("AAA", series[0], mu=0.01),
        _inst("BBB", series[1], mu=0.010001),
    ]
    costly = {"brokers": {"paper": {"tariffs": {"sim": {"commission_rate": "0.5"}}}}}
    held = construct(
        names,
        method="mean_variance",
        capital=Decimal("10000"),
        constraints=LOOSE,
        current_weights={"AAA": 0.5, "BBB": 0.5},
        broker="paper",
        tariff="sim",
        cost_table=costly,
        risk_aversion=8.0,
    )
    assert held["status"] == "ok"
    assert held["proposed_rebalance"] is False
    assert "издержек" in held["rebalance_reason"]
    assert held["orders"] == []
    cheap = construct(
        [_inst("AAA", series[0], mu=0.20), _inst("BBB", series[1], mu=0.0)],
        method="mean_variance",
        capital=Decimal("10000"),
        constraints=LOOSE,
        current_weights={"AAA": 0.0, "BBB": 1.0},
        broker="paper",
        tariff="sim",
        cost_table=COST,
        risk_aversion=1.0,
    )
    assert cheap["status"] == "ok"
    assert cheap["proposed_rebalance"] is True
    assert cheap["orders"]
    assert filter_wording(cheap["note"]) == []


def test_missing_tariff_does_not_invent_a_commission():
    book = construct(
        [_inst("AAA", _panel(16, 15), mu=0.05), _inst("BBB", _panel(16, 16), mu=0.01)],
        method="equal_weight",
        capital=Decimal("1000"),
        constraints=LOOSE,
        broker="unknown",
        tariff="unknown",
        cost_table={"brokers": {}},
    )
    assert book["costs"]["status"] == "нет данных"
    assert book["proposed_rebalance"] is False
    assert book["tax"]["year"]["tax_cash"] is None or book["tax"]["iis"]["tax_cash"] is None


def test_fifo_netting_and_long_term_base_without_a_rate():
    lots = [
        TaxLot("old", "AAA", Decimal("2"), Decimal("20"), date(2020, 1, 1)),
        TaxLot("new", "AAA", Decimal("2"), Decimal("40"), date(2025, 6, 1)),
    ]
    rows = fifo_realize(
        lots,
        ticker="AAA",
        sell_qty=Decimal("3"),
        sale_price=Decimal("15"),
        sold_on=date(2026, 10, 6),
    )
    assert rows[0]["lot_id"] == "old"
    assert Decimal(rows[0]["qty"]) == Decimal("2")
    assert rows[1]["lot_id"] == "new"
    loss = [{"year": "2026", "result": "-40.00", "long_term": "false", "full_years": "1"}]
    gain = [{"year": "2026", "result": "100.00", "long_term": "true", "full_years": "4"}]
    base = tax_base_for_year(loss + gain, 2026)
    assert Decimal(base["net_before_relief"]) == Decimal("60.00")
    assert base["tax_cash"] is None
    assert "224" in str(base["tax_cash_reason"])
    assert base["relief_applied"] is True


def _profit_lot(profit: Decimal, *, acquired: date, sold: date, resident: bool) -> dict:
    cost = Decimal("1000.00")
    rows = fifo_realize(
        [TaxLot("lot", "AAA", Decimal("1"), cost, acquired)],
        ticker="AAA",
        sell_qty=Decimal("1"),
        sale_price=cost + profit,
        sold_on=sold,
    )
    return tax_base_for_year(rows, sold.year, resident=resident)


def test_ndfl_resident_profit_below_and_above_2_400_000():
    """НК РФ ст. 224, 214.1, 219.1. Сверка 2026-10-06. Цифры основателя 2026-10-07.

    One securities book with profit below 2 400 000 RUB and one above.
    Resident cash is 13% up to the bracket and 15% on the excess.
    """
    sold = date(2026, 10, 6)
    short = date(2026, 1, 6)
    below = _profit_lot(Decimal("1000000.00"), acquired=short, sold=sold, resident=True)
    above = _profit_lot(Decimal("3000000.00"), acquired=short, sold=sold, resident=True)
    assert Decimal(str(below["tax_base"])) == Decimal("1000000.00")
    assert Decimal(str(below["tax_cash"])) == Decimal("130000.00")
    assert Decimal(str(above["tax_base"])) == Decimal("3000000.00")
    assert Decimal(str(above["tax_cash"])) == Decimal("402000.00")
    nonresident = _profit_lot(Decimal("1000000.00"), acquired=short, sold=sold, resident=False)
    nonresident_above = _profit_lot(Decimal("3000000.00"), acquired=short, sold=sold, resident=False)
    assert Decimal(str(nonresident["tax_cash"])) == Decimal("300000.00")
    assert Decimal(str(nonresident_above["tax_cash"])) == Decimal("900000.00")
    dividends_below = dividend_ndfl(Decimal("1000000.00"), resident=True)
    dividends_above = dividend_ndfl(Decimal("3000000.00"), resident=True)
    dividends_nonresident = dividend_ndfl(Decimal("1000000.00"), resident=False)
    assert Decimal(str(dividends_below["tax_cash"])) == Decimal("130000.00")
    assert Decimal(str(dividends_above["tax_cash"])) == Decimal("402000.00")
    assert Decimal(str(dividends_nonresident["tax_cash"])) == Decimal("150000.00")
    held = _profit_lot(Decimal("10000000.00"), acquired=date(2023, 10, 6), sold=sold, resident=True)
    assert held["relief_applied"] is True
    assert Decimal(str(held["relief"])) == Decimal("9000000.00")
    assert Decimal(str(held["tax_base"])) == Decimal("1000000.00")
    assert Decimal(str(held["tax_cash"])) == Decimal("130000.00")
    assert "2026-10-06" in str(below["citation_224"])
    assert "224" in str(below["citation_224"])


def test_lot_rounding_changes_qty_not_pre_round_weights():
    book_a = construct(
        [_inst("AAA", lot="10"), _inst("BBB", lot="10")],
        method="equal_weight",
        capital=Decimal("1000"),
        constraints=LOOSE,
        broker="paper",
        tariff="sim",
        cost_table=COST,
    )
    book_b = construct(
        [_inst("AAA", lot="10"), _inst("BBB", lot="10")],
        method="equal_weight",
        capital=Decimal("10000"),
        constraints=LOOSE,
    )
    assert book_a["weights"] == book_b["weights"]


def test_property_grid_sums_and_signs():
    rng = np.random.default_rng(36)
    for draw in range(6):
        n = int(rng.integers(2, 5))
        series = [_panel(28, 100 + draw * 10 + i, float(rng.uniform(0.005, 0.03))) for i in range(n)]
        names = [_inst(f"N{i}", series[i], mu=float(rng.normal(0.0, 0.01))) for i in range(n)]
        for method in ("equal_weight", "equal_risk_contribution", "hrp", "mean_variance", "cvar"):
            book = construct(
                names,
                method=method,
                capital=Decimal("25000"),
                constraints=ConstraintSet(name_cap=Decimal("0.8"), allow_shorts=False),
            )
            assert book["status"] == "ok", (method, book["reason"])
            total = sum(Decimal(v) for v in book["weights"].values())
            assert abs(total - 1) < Decimal("0.0001")
            assert all(Decimal(v) >= 0 for v in book["weights"].values())


def test_build_for_user_is_on_the_act_path(monkeypatch):
    reset_for_tests()
    reset_act()
    get_book().reset()
    assert is_enabled("qa_target_portfolio") is True
    assert is_enabled("qa_act_model_profile") is False
    save_profile(
        "u-36",
        {
            "horizon": "3y",
            "risk_tolerance": "moderate",
            "max_position_pct": "0.60",
            "max_crisis_loss_pct": "0.15",
        },
    )
    from app.services.portfolio_book.service import ensure_account, record_transaction
    from datetime import datetime, timezone

    ensure_account(account_id="p36", user_id="u-36", venue="paper", mode="paper")
    record_transaction(
        account_id="p36",
        user_id="u-36",
        mode="paper",
        venue="paper",
        external_id="s1",
        kind="trade",
        instrument_id="AAA",
        ticker="AAA",
        qty="10",
        amount="100",
        ccy="RUB",
        event_time=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    record_transaction(
        account_id="p36",
        user_id="u-36",
        mode="paper",
        venue="paper",
        external_id="s2",
        kind="trade",
        instrument_id="BBB",
        ticker="BBB",
        qty="10",
        amount="100",
        ccy="RUB",
        event_time=datetime(2026, 1, 3, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        "app.services.target_portfolio.service.load_market_price",
        lambda ticker: (Decimal("10"), "display_allowed", True),
    )
    from app.services.risk_engine.series import put_series

    put_series("AAA", list(_panel(20, 21)))
    put_series("BBB", list(_panel(20, 22)))
    book = build_for_user("u-36", mode="paper", method="equal_weight")
    assert book["status"] == "ok"
    assert book["target_source"] == "user"
    batch = propose(user_id="u-36", mode="paper", target_source="user", method="hrp")
    assert batch["target_source"] == "user"
    assert batch["target_book"]["target_source"] == "user"
    assert "target_book" in batch
    text = (REPO / "backend/app/services/target_portfolio/service.py").read_text(encoding="utf-8").lower()
    for phrase in FORBIDDEN:
        assert phrase not in text
    reset_act()
    get_book().reset()


def test_texts_do_not_use_advice_language():
    root = REPO / "backend/app/services/target_portfolio"
    for path in root.glob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        for phrase in FORBIDDEN:
            assert phrase not in text
    assert "это возвращает портфель к вашим правилам" in (
        REPO / "backend/app/services/target_portfolio/service.py"
    ).read_text(encoding="utf-8")
