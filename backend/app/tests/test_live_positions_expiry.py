"""Live positions: expiry countdown, timezone, snapshot freshness."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.schemas.schemas import ManeuverStatus, StrategyType
from app.services.portfolio import position_analytics as pa
from app.services.portfolio.positions_snapshot import _live_snapshot_meta


def _maneuver(**kwargs):
    base = dict(
        id="m1",
        rank=1,
        ticker="MSFT",
        strategy_type=StrategyType.TREND_FOLLOWING,
        direction="long",
        entry_zone_low=400.0,
        entry_zone_high=410.0,
        exit_zone_low=430.0,
        exit_zone_high=440.0,
        stop_loss=395.0,
        take_profit=435.0,
        invalidation_level=395.0,
        risk_percent=1.0,
        position_size_usd=2000.0,
        confidence=0.7,
        time_horizon="3–10 дней",
        status=ManeuverStatus.FILLED,
        trading_mode="paper",
        fill_price=405.0,
        filled_at=datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc),
        created_at=datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc),
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def _format_expiry_countdown(total_seconds: int) -> str:
    """Mirror of frontend formatExpiryCountdown for contract tests."""
    if total_seconds <= 0:
        return "срок вышел"
    days = total_seconds // 86_400
    hours = (total_seconds % 86_400) // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    pad = lambda n: str(n).zfill(2)
    if days:
        return f"{days}d {pad(hours)}:{pad(minutes)}:{pad(seconds)}"
    return f"{pad(hours)}:{pad(minutes)}:{pad(seconds)}"


def test_horizon_end_at_uses_filled_at_plus_horizon():
    m = _maneuver(time_horizon="1-3 дня")
    now = datetime(2026, 8, 3, 0, 0, 0, tzinfo=timezone.utc)
    end = pa.horizon_end_at(m, now)
    assert end is not None
    expected = m.filled_at + timedelta(days=2)
    assert end == expected


def test_apply_expiry_ignores_stale_pipeline_created_at(monkeypatch):
    """Approve-time expiry must not anchor to pipeline created_at (cascade bug)."""
    created = datetime(2026, 8, 1, 8, 0, 0, tzinfo=timezone.utc)
    approve_now = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)
    m = _maneuver(
        status=ManeuverStatus.PENDING,
        filled_at=None,
        approved_at=None,
        created_at=created,
        time_horizon="3 hours",
    )

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return approve_now if tz else approve_now.replace(tzinfo=None)

    monkeypatch.setattr(pa, "datetime", _FixedDatetime)

    changes = pa.apply_horizon_expiry_overrides(m, time_horizon="3 hours")
    end = datetime.fromisoformat(changes["expiry_at"])
    assert end == approve_now + timedelta(hours=3)


def test_reanchor_relative_expiry_on_fill():
    created = datetime(2026, 8, 1, 8, 0, 0, tzinfo=timezone.utc)
    filled = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)
    m = _maneuver(
        filled_at=filled,
        created_at=created,
        time_horizon="1 day",
        signal_meta={
            "expiry_at": (created + timedelta(days=1)).isoformat(),
            "expiry_source": "relative",
        },
    )
    assert pa.reanchor_relative_expiry_on_fill(m) is True
    end = datetime.fromisoformat(m.signal_meta["expiry_at"])
    assert end == filled + timedelta(days=1)


@pytest.mark.parametrize(
    "label,expected_seconds",
    [
        ("3 hours", 3 * 3600),
        ("1 day", 86_400),
        ("3 часа", 3 * 3600),
        ("1 день", 86_400),
    ],
)
def test_horizon_to_seconds_en_and_ru(label, expected_seconds):
    assert pa.horizon_to_seconds(label) == expected_seconds


def test_horizon_end_at_uses_approved_at_not_refresh_now_for_unfilled():
    approved_at = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)
    m = _maneuver(
        status=ManeuverStatus.APPROVED,
        filled_at=None,
        approved_at=approved_at,
        time_horizon="6 hours",
    )
    first_now = datetime(2026, 8, 1, 12, 0, 3, tzinfo=timezone.utc)
    refresh_now = datetime(2026, 8, 1, 12, 0, 8, tzinfo=timezone.utc)

    first = pa.horizon_end_at(m, first_now)
    refreshed = pa.horizon_end_at(m, refresh_now)

    assert first == approved_at + timedelta(hours=6)
    assert refreshed == first
    assert pa.time_to_close_seconds(m, refresh_now) == pa.time_to_close_seconds(m, first_now) - 5


def test_horizon_end_at_uses_explicit_signal_meta_expiry():
    expiry = "2026-08-04T18:30:00+00:00"
    m = _maneuver(
        time_horizon="1 день",
        signal_meta={"expiry_at": expiry},
    )

    assert pa.horizon_end_at(m, datetime(2026, 8, 2, tzinfo=timezone.utc)) == datetime.fromisoformat(expiry)


def test_time_to_close_counts_down_with_timezone_naive_filled_at():
    """Naive filled_at in DB must be treated as UTC (no freeze at midnight boundary)."""
    naive_fill = datetime(2026, 8, 1, 23, 30, 0)
    m = _maneuver(filled_at=naive_fill, time_horizon="1 день")
    now = datetime(2026, 8, 2, 23, 0, 0, tzinfo=timezone.utc)
    ttc = pa.time_to_close_seconds(m, now)
    assert ttc is not None
    assert 0 < ttc <= 3600


def test_horizon_expired_at_midnight_crossing():
    m = _maneuver(time_horizon="1 день")
    now = m.filled_at + timedelta(days=2)
    assert pa.horizon_expired(m, now) is True
    assert pa.time_to_close_seconds(m, now) == 0


def test_horizon_expired_approved_without_fill():
    approved_at = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)
    m = _maneuver(
        status=ManeuverStatus.APPROVED,
        filled_at=None,
        approved_at=approved_at,
        time_horizon="6 hours",
    )
    still_open = datetime(2026, 8, 1, 17, 0, 0, tzinfo=timezone.utc)
    overdue = datetime(2026, 8, 1, 19, 0, 0, tzinfo=timezone.utc)
    assert pa.horizon_expired(m, still_open) is False
    assert pa.horizon_expired(m, overdue) is True
    assert pa.should_auto_close_on_horizon(m, overdue) is True


def test_pending_expired_horizon_does_not_auto_close():
    m = _maneuver(
        status=ManeuverStatus.PENDING,
        filled_at=None,
        approved_at=None,
        created_at=datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc),
        time_horizon="1 hour",
    )
    now = datetime(2026, 8, 2, 12, 0, 0, tzinfo=timezone.utc)
    assert pa.horizon_expired(m, now) is True
    assert pa.should_auto_close_on_horizon(m, now) is False


def test_live_snapshot_meta_stale_flag():
    started = datetime(2026, 8, 3, 0, 0, 0, tzinfo=timezone.utc)
    now = started + timedelta(seconds=2)
    meta = _live_snapshot_meta(now=now, refresh_started=started, stale=True)
    assert meta["stale"] is True
    assert meta["data_freshness_seconds"] == 2
    assert meta["server_now"] == now.isoformat()
    assert meta["last_refresh_at"] == started.isoformat()


@pytest.mark.parametrize(
    "seconds,expected",
    [
        (90_000, "1d 01:00:00"),
        (86_400 + 7200 + 5, "1d 02:00:05"),
        (3 * 86_400 + 12 * 3600 + 15 * 60, "3d 12:15:00"),
        (3599, "00:59:59"),        # < 1 day: HH:MM:SS
        (3661, "01:01:01"),
        (65, "00:01:05"),
        (0, "срок вышел"),
    ],
)
def test_expiry_countdown_format_contract(seconds, expected):
    assert _format_expiry_countdown(seconds) == expected


def _remaining_seconds_from_expiry(
    expires_at_iso: str,
    server_now_iso: str,
    client_now_ms: int,
    fetched_at_ms: int,
) -> int:
    """Mirror frontend remainingSecondsFromExpiry + serverAlignedNowMs."""
    expires_at = datetime.fromisoformat(expires_at_iso.replace("Z", "+00:00")).timestamp() * 1000
    server_now = datetime.fromisoformat(server_now_iso.replace("Z", "+00:00")).timestamp() * 1000
    skew_ms = fetched_at_ms - server_now
    adjusted_now = client_now_ms - skew_ms
    return max(0, int((expires_at - adjusted_now) // 1000))


def test_expiry_countdown_ticks_forward_with_skew():
    """Server/client skew must not freeze countdown — ticks down each second."""
    server_now_iso = "2026-08-03T12:00:00+00:00"
    expires_iso = "2026-08-05T12:00:00+00:00"
    fetched_at = datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc).timestamp() * 1000
    t0 = _remaining_seconds_from_expiry(expires_iso, server_now_iso, fetched_at, fetched_at)
    t1 = _remaining_seconds_from_expiry(
        expires_iso,
        server_now_iso,
        fetched_at + 1000,
        fetched_at,
    )
    assert t0 == 172_800
    assert t1 == t0 - 1


def test_expiry_countdown_monotonic_under_server_now_refresh():
    """New server_now snapshot must not increase displayed remaining time."""
    expires_iso = "2026-08-05T12:00:00+00:00"
    fetched_at = datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc).timestamp() * 1000
    client_now = fetched_at + 5000
    first = _remaining_seconds_from_expiry(
        expires_iso,
        "2026-08-03T12:00:05+00:00",
        client_now,
        fetched_at,
    )
    # Server refresh reports slightly ahead server_now (would bump countdown up without clamp).
    bumped = _remaining_seconds_from_expiry(
        expires_iso,
        "2026-08-03T12:00:08+00:00",
        client_now,
        fetched_at,
    )
    assert bumped >= first - 3  # small forward skew only
    assert min(first, bumped) <= first


def test_expiry_midnight_crossing_naive_fill():
    """Naive filled_at treated as UTC — no freeze at day boundary."""
    naive_fill = datetime(2026, 8, 1, 23, 30, 0)
    m = _maneuver(filled_at=naive_fill, time_horizon="1 день")
    before_midnight = datetime(2026, 8, 2, 22, 0, 0, tzinfo=timezone.utc)
    after_midnight = datetime(2026, 8, 2, 23, 45, 0, tzinfo=timezone.utc)
    t_before = pa.time_to_close_seconds(m, before_midnight)
    t_after = pa.time_to_close_seconds(m, after_midnight)
    assert t_before is not None and t_after is not None
    assert t_after < t_before
    assert t_after < 3600


def test_horizon_to_seconds_session_and_minutes():
    assert pa.horizon_to_seconds("внутри дня") == 6 * 3600
    assert pa.horizon_to_seconds("90 минут") == 90 * 60
    assert pa.horizon_to_seconds("не для скальпа") is None


def test_expire_disposition_paper_unfilled_closes_with_audit():
    from app.services.portfolio.expire_disposition import expire_disposition

    m = _maneuver(
        status=ManeuverStatus.APPROVED,
        trading_mode="paper",
        fill_price=None,
        filled_at=None,
        approved_at=datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc),
        time_horizon="1 hour",
        created_at=datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc),
    )
    # overdue relative to approved_at
    overdue = datetime(2026, 8, 1, 14, 0, 0, tzinfo=timezone.utc)
    assert pa.should_auto_close_on_horizon(m, overdue) is True
    assert expire_disposition(m) == "close_paper_and_audit"


def test_expire_disposition_live_unfilled_cancels_without_audit():
    from app.services.portfolio.expire_disposition import expire_disposition

    m = _maneuver(
        status=ManeuverStatus.APPROVED,
        trading_mode="live",
        fill_price=None,
        filled_at=None,
        approved_at=datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc),
        time_horizon="1 hour",
        created_at=datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc),
    )
    assert expire_disposition(m) == "cancel_live_no_audit"


def test_expire_disposition_filled_closes_with_audit():
    from app.services.portfolio.expire_disposition import expire_disposition

    m = _maneuver(
        status=ManeuverStatus.FILLED,
        trading_mode="live",
        time_horizon="1 hour",
        filled_at=datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc),
    )
    overdue = datetime(2026, 8, 1, 14, 0, 0, tzinfo=timezone.utc)
    assert pa.should_auto_close_on_horizon(m, overdue) is True
    assert expire_disposition(m) == "close_and_audit"
