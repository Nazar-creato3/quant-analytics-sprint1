"""FRED local macro cache."""
from __future__ import annotations

import json
from pathlib import Path

from app.services.market_data.fred_bulk_store import latest_observation, overview_macro_rows, store_status


def test_overview_rows_from_cache(tmp_path: Path, monkeypatch) -> None:
    from app.services.market_data import fred_bulk_store as store

    root = tmp_path / "fred"
    (root / "current").mkdir(parents=True)
    for sid, label, val, day in (
        ("UNRATE", "безработица США, %", "4.2", "2026-08-31"),
        ("FEDFUNDS", "ставка ФРС, %", "5.25", "2026-09-15"),
        ("VIXCLS", "индекс страха VIX", "14.5", "2026-09-15"),
        ("DGS10", "доходность 10 лет, %", "4.1", "2026-09-15"),
    ):
        (root / "current" / f"{sid}.json").write_text(
            json.dumps(
                {
                    "series_id": sid,
                    "label": label,
                    "source": "fred_http",
                    "observations": [{"date": day, "value": val}],
                }
            ),
            encoding="utf-8",
        )
    monkeypatch.setattr(store, "bulk_root", lambda: root)
    rows = overview_macro_rows()
    assert len(rows) == 4
    assert latest_observation("VIXCLS")["value"] == 14.5
    st = store_status()
    assert st["root"] == str(root)
