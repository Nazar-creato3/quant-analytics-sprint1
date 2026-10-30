"""Demo fixture label. These numbers are the tracked file, not an exchange quote."""
from __future__ import annotations

import json

import pytest

from app.services.e2e_demo.prepare_role import require_app_db_password
from app.services.e2e_demo.seed import load_demo_market, read_fixture


def test_demo_fixture_is_labeled_and_has_history(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "app.services.market_data.equity_eod_store.bulk_root",
        lambda: tmp_path,
    )
    loaded = load_demo_market()
    assert loaded["label"] == "e2e/demo"
    assert loaded["bars"] > 0
    fixture = read_fixture()
    assert fixture["not_a_live_quote"] is True
    assert fixture["label"] == "e2e/demo"
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["label"] == "e2e/demo"
    assert manifest["symbols"]


def test_apply_demo_book_skips_second_factor_rebuild(monkeypatch, tmp_path):
    import app.services.e2e_demo.seed as seed

    monkeypatch.setattr(
        "app.services.market_data.equity_eod_store.bulk_root",
        lambda: tmp_path,
    )
    seed._market_cache = None
    seed._side_loaded = False
    seed.apply_demo_book("e2e-user-a")
    calls = {"n": 0}

    def boom():
        calls["n"] += 1
        raise AssertionError("rebuild must not run twice")

    monkeypatch.setattr("app.services.factor_lens.ingest.rebuild_from_fixture", boom)
    seed.apply_demo_book("e2e-user-b")
    assert calls["n"] == 0


def test_apply_demo_book_does_not_import_quantlib(monkeypatch, tmp_path):
    import sys

    import app.services.e2e_demo.seed as seed

    monkeypatch.setattr(
        "app.services.market_data.equity_eod_store.bulk_root",
        lambda: tmp_path,
    )
    seed._market_cache = None
    seed._side_loaded = False
    sys.modules.pop("QuantLib", None)
    attached = seed.apply_demo_book("e2e-user")
    assert attached["tickers"]
    assert "QuantLib" not in sys.modules


def test_prepare_role_refuses_outside_demo(monkeypatch):
    monkeypatch.delenv("QA_E2E_DEMO", raising=False)
    monkeypatch.setenv("APP_DB_PASSWORD", "abc123")
    with pytest.raises(SystemExit):
        require_app_db_password()


def test_prepare_role_refuses_symbol_password(monkeypatch):
    monkeypatch.setenv("QA_E2E_DEMO", "true")
    monkeypatch.setenv("APP_DB_PASSWORD", "bad-password")
    with pytest.raises(SystemExit):
        require_app_db_password()
