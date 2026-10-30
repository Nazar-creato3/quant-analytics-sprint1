from __future__ import annotations

import json
import time
from pathlib import Path

from app.services.screener.service import export_csv, filter_rows, reset_saved, save_screen, screen

REPO = Path(__file__).resolve().parents[3]


def test_missing_pe_is_no_data_not_zero():
    payload = screen({"country": "RU", "limit": 50})
    sber = next(r for r in payload["items"] if r["symbol"] == "SBER")
    assert sber["pe"] is None
    assert sber["pe_status"] == "нет данных"
    assert sber["pe"] != 0
    assert sber["fundamentals_source"]
    assert sber["fundamentals_as_of"]
    assert sber["beta"] == 1.05
    assert sber["risk_source"] == "risk_engine.fhs.v1"


def test_beta_filter_excludes_missing_not_as_zero():
    rows = [
        {"symbol": "A", "beta": None, "country": "US"},
        {"symbol": "B", "beta": 1.8, "country": "US"},
        {"symbol": "C", "beta": 0.2, "country": "US"},
    ]
    got = filter_rows(rows, {"betaMoreThan": 1.5, "limit": 10})
    assert [r["symbol"] for r in got] == ["B"]


def test_tech_and_es_filters():
    payload = screen({"sector": "Technology", "esMoreThan": 0.05, "limit": 20})
    symbols = [r["symbol"] for r in payload["items"]]
    assert "NVDA" in symbols
    assert "AAPL" not in symbols


def test_saved_screens_are_per_user():
    reset_saved()
    save_screen("u1", "tech", {"sector": "Technology"})
    save_screen("u2", "ru", {"country": "RU"})
    from app.services.screener.service import list_saved

    assert [s["name"] for s in list_saved("u1")] == ["tech"]
    assert [s["name"] for s in list_saved("u2")] == ["ru"]


def test_export_csv_keeps_blank_for_missing():
    payload = screen({"country": "RU", "limit": 80})
    sber = [r for r in payload["items"] if r["symbol"] == "SBER"]
    text = export_csv(sber)
    assert "SBER" in text
    assert "нет данных" in text


def test_screener_budget():
    budget = json.loads((REPO / "docs" / "qa" / "perf-budgets.json").read_text(encoding="utf-8"))
    spec = budget["screener_ms"]
    rows = [{"symbol": f"T{i}", "country": "US", "beta": 1.0 + (i % 5) / 10} for i in range(int(spec["n"]))]
    t0 = time.perf_counter()
    filter_rows(rows, {"betaMoreThan": 1.2, "limit": 300})
    elapsed = (time.perf_counter() - t0) * 1000
    assert elapsed < float(spec["max_ms"]), elapsed
