"""GA16-348: pipeline status messages must be Russian without Celery/SIGKILL/raw."""

from pathlib import Path


def test_pipeline_status_client_copy():
    text = Path("app/api/v1/endpoints/pipeline.py").read_text(encoding="utf-8")
    assert "User not found" not in text
    assert "Could not queue pipeline" not in text
    assert "celery-pipeline" not in text
    assert "Pipeline worker ran out of memory (SIGKILL)" not in text
    assert "msg = raw" not in text
    assert "Анализ завершён." in text
    assert "Пользователь не найден" in text
