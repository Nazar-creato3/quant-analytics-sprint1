"""Admin fleet book — usefulness without leaking into the maneuver factory."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.audit.fleet import (
    calibrate_closed,
    concentrate_holdings,
    snapshot_is_fresh,
    user_overlaps,
)


def test_concentration_counts_unique_users():
    rows = concentrate_holdings(
        [
            ("AAPL", "u1", 1000),
            ("AAPL", "u1", 200),
            ("AAPL", "u2", 500),
            ("MSFT", "u2", 100),
        ]
    )
    apple = next(r for r in rows if r["ticker"] == "AAPL")
    assert apple["user_count"] == 2
    assert apple["notional_usd"] == 1700.0


def test_overlaps_need_two_shared_names():
    pairs = user_overlaps(
        {"u1": {"AAPL", "MSFT", "NVDA"}, "u2": {"AAPL", "MSFT"}, "u3": {"AAPL"}},
        emails={"u1": "a@x", "u2": "b@x", "u3": "c@x"},
    )
    assert pairs[0]["shared_count"] == 2
    assert {pairs[0]["user_a"], pairs[0]["user_b"]} == {"a@x", "b@x"}
    assert all("c@x" not in (p["user_a"], p["user_b"]) or p["shared_count"] >= 2 for p in pairs)


def test_calibration_is_post_hoc_only():
    cal = calibrate_closed(
        [
            {"ticker": "NVDA", "strategy": "momentum", "realized_pnl": 80, "confidence": 0.7},
            {"ticker": "NVDA", "strategy": "momentum", "realized_pnl": -20, "confidence": 0.6},
            {"ticker": "XOM", "strategy": "macro", "realized_pnl": -50, "confidence": 0.55},
        ]
    )
    assert cal["trade_count"] == 3
    assert cal["win_rate"] == round(1 / 3, 4)
    worst = cal["by_ticker"][0]
    assert worst["ticker"] == "XOM"


def test_pipeline_modules_do_not_import_fleet():
    import ast
    from pathlib import Path

    app_root = Path(__file__).resolve().parents[1]
    roots = [
        app_root / "tasks" / "pipeline.py",
        app_root / "services" / "risk" / "maneuver_generator.py",
    ]
    for path in roots:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "fleet" not in alias.name
            if isinstance(node, ast.ImportFrom) and node.module:
                assert "fleet" not in node.module


def test_public_snapshot_strips_user_ids():
    from app.api.v1.endpoints.fleet_audit import _public_snapshot

    out = _public_snapshot(
        {
            "accounts": [{"user_id": "secret", "email": "a@x", "open_maneuvers": 1}],
            "feeds_maneuver_factory": True,
        },
        limit=10,
    )
    assert "user_id" not in out["accounts"][0]
    assert out["feeds_maneuver_factory"] is False
    assert out["venue_api_called"] is False


def test_stale_fleet_snapshot_is_not_fresh():
    now = datetime.now(timezone.utc)
    assert snapshot_is_fresh({"as_of": now.isoformat()}) is True
    stale = now - timedelta(hours=40)
    assert snapshot_is_fresh({"as_of": stale.isoformat()}) is False
    assert snapshot_is_fresh({"as_of": "not-a-date"}) is False
    assert snapshot_is_fresh(None) is False


def test_fleet_router_is_admin_gated():
    import inspect

    from app.api.v1.endpoints.fleet_audit import get_fleet_audit, router
    from app.core.deps import require_admin

    assert router.prefix == "/admin/fleet-audit"
    source = inspect.getsource(get_fleet_audit)
    assert "require_admin" in source
    assert require_admin is not None
