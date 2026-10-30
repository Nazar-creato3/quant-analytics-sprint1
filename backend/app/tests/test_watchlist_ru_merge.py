"""watchlist_ru only adds tickers: Russian first, own order kept, --full fills the main US set."""
from app.scripts.watchlist_ru import GLOBAL, RU_FIRST, merge


def test_russian_first_nothing_removed():
    out = merge(["TSLA", "SBER", "XYZ"])
    assert out[: len(RU_FIRST)] == RU_FIRST
    assert "TSLA" in out and "XYZ" in out
    assert len(out) == len(set(out))


def test_full_adds_missing_global_once():
    out = merge(["SPY", "BTC-USD"], full=True)
    assert set(GLOBAL) <= set(out)
    assert out.count("SPY") == 1
    assert out.index("SPY") < out.index("AAPL")  # user's own order before the additions
