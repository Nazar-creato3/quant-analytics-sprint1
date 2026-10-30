from datetime import datetime, timedelta, timezone

from app.services.pdn_retention.job import run_retention_job
from app.services.pdn_retention.policy import is_expired

NOW = datetime(2026, 10, 10, tzinfo=timezone.utc)


def test_account_open_never_expires():
    assert is_expired(kind="account_open", created_at=NOW - timedelta(days=4000), now=NOW) is False


def test_after_delete_within_30_days_kept():
    assert is_expired(kind="account_after_delete", created_at=NOW - timedelta(days=10), now=NOW) is False
    assert is_expired(kind="account_after_delete", created_at=NOW - timedelta(days=31), now=NOW) is True


def test_security_logs_six_months():
    assert is_expired(kind="security_logs", created_at=NOW - timedelta(days=100), now=NOW) is False
    assert is_expired(kind="security_logs", created_at=NOW - timedelta(days=200), now=NOW) is True


def test_payments_five_years():
    assert is_expired(kind="payments", created_at=NOW - timedelta(days=1000), now=NOW) is False
    assert is_expired(kind="payments", created_at=NOW - timedelta(days=2000), now=NOW) is True


def test_waitlist_unsubscribe_or_six_months_after_launch():
    assert is_expired(kind="waitlist_unsubscribed", created_at=NOW, now=NOW) is True
    launch = NOW - timedelta(days=200)
    assert is_expired(kind="waitlist_after_launch", created_at=NOW, now=NOW, launch_at=launch) is True
    assert is_expired(
        kind="waitlist_after_launch", created_at=NOW, now=NOW, launch_at=NOW - timedelta(days=10)
    ) is False


def test_interviews_six_months():
    assert is_expired(kind="interviews", created_at=NOW - timedelta(days=200), now=NOW) is True


def test_background_job_returns_purge_ids():
    rows = [
        {"id": "a", "kind": "account_after_delete", "created_at": NOW - timedelta(days=40)},
        {"id": "b", "kind": "payments", "created_at": NOW - timedelta(days=10)},
    ]
    result = run_retention_job(rows, now=NOW, apply=False)
    assert result["purged"] == 1
    assert result["purge_ids"] == ["a"]


def test_nightly_job_scans_waitlist_not_empty_list() -> None:
    from app.services.waitlist.service import open_fixture, reset, unsubscribe
    from app.tasks.pdn_retention import run_pdn_retention

    reset()
    row = open_fixture(
        email="ada@example.test",
        name=None,
        broker="tbank",
        portfolio_range="1",
        consent=True,
        honeypot="",
    )
    unsubscribe(row["token"])
    out = run_pdn_retention()
    assert out["scanned"] >= 1
    assert out["purged"] >= 1
    assert "ada@example.test" not in str(out)
