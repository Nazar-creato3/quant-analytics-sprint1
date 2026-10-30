"""GA16-267: failed backtest metrics must not carry exception text."""

from app.tasks.backtest import failed_backtest_metrics


def test_failed_backtest_metrics_has_no_exception_text():
    metrics = failed_backtest_metrics()
    assert metrics == {"failed": True}
    assert "error" not in metrics
    dumped = str(metrics)
    assert "Traceback" not in dumped
    assert "Exception" not in dumped
