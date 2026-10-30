from app.services.fundamental_data.native_sec_finra import pad_cik
from app.services.market_data.stooq_client import stooq_symbol
from app.services.risk.maneuver_generator import ManeuverGenerator
from app.services.terminal_platform.providers.public_macro import _jsonstat_time_values, _sdmx_observations


def test_pad_cik():
    assert pad_cik(320193) == "0000320193"
    assert pad_cik("320193") == "0000320193"


def test_stooq_symbol_us_default():
    assert stooq_symbol("AAPL") == "aapl.us"
    assert stooq_symbol("VOD.UK") == "vod.uk"


def test_jsonstat_time_values():
    payload = {
        "value": {"0": 2.1, "1": 2.4},
        "dimension": {"time": {"category": {"index": {"2024-01": 0, "2024-02": 1}}}},
    }
    rows = _jsonstat_time_values(payload)
    assert rows[0]["value"] == 2.1
    assert rows[1]["date"] == "2024-02"


def test_sdmx_empty_safe():
    assert _sdmx_observations({}) == []


def test_horizon_profiles_four_windows():
    gen = ManeuverGenerator.__new__(ManeuverGenerator)
    profiles = gen._horizon_profile("momentum")
    assert set(profiles) == {"скальп", "день", "свинг", "долго"}
    assert gen._pick_horizon("momentum") == profiles["свинг"]


def test_coingecko_demo_uses_query_not_headers():
    from app.services.market_data.http_providers import CoinGeckoClient

    client = CoinGeckoClient()
    client._api_key = "CG-test-demo-key"
    assert "x-cg-demo-api-key" not in client._auth_query()
    assert client._auth_query() == {"x_cg_demo_api_key": "CG-test-demo-key"}
    assert client._base == "https://api.coingecko.com/api/v3"


def test_overview_rebase_and_regime():
    from app.services.market_data.market_overview import rebase_closes, regime_from_board

    series = rebase_closes([("a", 100.0), ("b", 110.0)])
    assert series[-1]["pct"] == 10.0
    risk_on = regime_from_board(
        {
            "us_equity": [{"symbol": "SPY", "price": 500, "change_pct": 0.8}],
            "fixed_income": [
                {"symbol": "HYG", "price": 70, "change_pct": 0.2},
                {"symbol": "TLT", "price": 90, "change_pct": -0.1},
            ],
        }
    )
    assert risk_on is not None
    assert "включают" in risk_on
    empty = regime_from_board(
        {"us_equity": [{"symbol": "SPY", "price": None, "change_pct": None}]}
    )
    assert empty is None


def test_overview_source_has_no_vendor_name() -> None:
    import inspect

    from app.services.market_data.market_overview import build_market_overview

    src = inspect.getsource(build_market_overview)
    assert "local_eod_or_stooq" not in src
    assert '"source": "котировки"' in src
