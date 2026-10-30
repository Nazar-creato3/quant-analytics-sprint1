from app.services.portfolio_book.store import get_book
from app.services.sample_portfolio import load_sample, sample_state, unload_sample


def test_sample_loads_and_unloads_without_touching_other_accounts():
    get_book().reset()
    st = sample_state("u-sample")
    assert st["sample_loaded"] is False and st["has_positions"] is False
    st = load_sample("u-sample")
    assert st["sample_loaded"] and st["has_positions"] and not st["has_own_positions"]
    tickers = {p.ticker for p in get_book().positions(user_id="u-sample", mode="paper")}
    assert {"SBER", "LKOH", "ROSN", "LQDT"} <= tickers
    load_sample("u-sample")  # idempotent
    assert len([p for p in get_book().positions(user_id="u-sample", mode="paper") if p.ticker == "SBER"]) == 1
    assert sample_state("someone-else")["has_positions"] is False
    st = unload_sample("u-sample")
    assert st["sample_loaded"] is False and st["has_positions"] is False
