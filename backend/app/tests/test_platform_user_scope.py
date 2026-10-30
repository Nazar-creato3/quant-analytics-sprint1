"""GA16-344: platform report/monitor packs are isolated by user_id."""
from __future__ import annotations

from pathlib import Path

from app.services.platform_desk.monitor import load_snapshot, persist_snapshot
from app.services.platform_desk.reporting import load_latest_client_pack, persist_client_pack


def test_client_pack_isolated_by_user(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("app.services.platform_desk.reporting._book_dir", lambda: tmp_path)
    persist_client_pack({"as_of": "2026-10-18", "holdings_n": 1, "secret": "alice"}, user_id="alice")
    persist_client_pack({"as_of": "2026-10-18", "holdings_n": 2, "secret": "bob"}, user_id="bob")

    alice = load_latest_client_pack(user_id="alice")
    bob = load_latest_client_pack(user_id="bob")
    assert alice is not None and alice["secret"] == "alice"
    assert bob is not None and bob["secret"] == "bob"
    assert load_latest_client_pack(user_id="carol") is None


def test_monitor_snapshot_isolated_by_user(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("app.services.platform_desk.monitor._dir", lambda: tmp_path)
    persist_snapshot({"freshness_ok": True, "tag": "a"}, user_id="alice")
    persist_snapshot({"freshness_ok": False, "tag": "b"}, user_id="bob")

    assert load_snapshot(user_id="alice")["tag"] == "a"
    assert load_snapshot(user_id="bob")["tag"] == "b"
    assert load_snapshot(user_id="carol") is None
