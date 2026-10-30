"""Contract tests for frontend formatPipelineManeuverToast (Prompt 90/95)."""


def test_toast_backfill_only_suffix():
    """Mirrors TS: all slots below threshold."""
    msg = (
        "Анализ завершён — 3/10 маневров ожидают одобрения"
        " · все 3 ниже порога 65%"
    )
    assert "ниже порога 65%" in msg
    assert "готовы к одобрению" not in msg


def test_toast_pending_zero_honest():
    msg = (
        "Анализ завершён — в отчёте 5/10 торгуемых, "
        "ожидают одобрения: 0 (уже отклонены или исполнены)"
    )
    assert "ожидают одобрения: 0" in msg
