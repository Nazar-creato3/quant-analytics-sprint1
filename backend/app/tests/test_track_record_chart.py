"""Tests for track record calibration chart."""
from __future__ import annotations

from app.services.track_record.calibration_chart import build_track_record_chart_data


class TestTrackRecordChart:
    def test_builds_chart_data(self):
        chart = build_track_record_chart_data()
        d = chart.to_dict()
        assert "calibration_bins" in d
        assert "rolling_accuracy" in d
        assert "drift_flag" in d

    def test_rolling_accuracy_has_windows(self):
        chart = build_track_record_chart_data()
        if chart.rolling_accuracy:
            windows = {p.window_days for p in chart.rolling_accuracy}
            assert windows.issubset({30, 90, 365})
