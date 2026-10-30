from datetime import date, datetime, timezone

from app.services.market_data import databento_book as db


def test_session_is_older_than_24h() -> None:
    # Friday 23 Oct 2026 22:00 UTC: Friday close is only 2h old → Thursday.
    assert db.session_for(datetime(2026, 10, 23, 22, 0, tzinfo=timezone.utc)) == date(2026, 10, 22)
    # Monday morning → Friday's close is > 24 h old.
    assert db.session_for(datetime(2026, 10, 26, 9, 0, tzinfo=timezone.utc)) == date(2026, 10, 23)


def test_parse_mbp10_pretty_and_fixed_point() -> None:
    line = '{"hd":{"ts_event":"2026-10-22T19:59:50.1Z","rtype":10},"levels":[{"bid_px":"190.11","ask_px":"190.13","bid_sz":200,"ask_sz":300},{"bid_px":190100000000,"ask_px":190140000000,"bid_sz":50,"ask_sz":0}]}'
    bids, asks, ts = db.parse_mbp10(line + "\n")
    assert bids == [(190.11, 200.0), (190.1, 50.0)]
    assert asks == [(190.13, 300.0)]
    assert ts.startswith("2026-10-22")
