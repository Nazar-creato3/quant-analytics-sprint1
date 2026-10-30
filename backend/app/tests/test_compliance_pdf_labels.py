"""GA16-296: compliance PDF must not expose internal layer/intent names."""

from pathlib import Path


def test_pdf_renderer_has_no_internal_jargon():
    text = Path("app/services/compliance_report/pdf_renderer.py").read_text(encoding="utf-8")
    for banned in (
        "DealIntent",
        "id={document.instrument_id}",
        "Max drawdown",
        "ExplainabilityLayer",
        "PredictionNarrator",
    ):
        assert banned not in text
    assert "Максимальная просадка" in text
