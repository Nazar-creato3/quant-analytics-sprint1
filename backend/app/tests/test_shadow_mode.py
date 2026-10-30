from __future__ import annotations

from pathlib import Path

from app.services.qa.shadow_mode import export_report, shadow_call


def test_shadow_records_delta(tmp_path: Path):
    path = tmp_path / "shadow.jsonl"
    out = shadow_call("var_demo", [1.0, 2.0], lambda x: 1.0, lambda x: 1.5, path=path)
    assert out == 1.0
    report = export_report(path)
    assert report["count"] == 1
    assert report["alerts"] == 1
    assert report["rows"][0]["delta"] == 0.5
