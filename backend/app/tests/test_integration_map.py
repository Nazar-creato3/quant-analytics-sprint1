"""INTEGRATION_MAP lists required modules and island claims stay explicit."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
MAP = REPO / "docs" / "qa" / "INTEGRATION_MAP.md"

REQUIRED = (
    "Риск (K4)",
    "K6",
    "K1",
    "59",
    "62",
    "60",
    "56",
    "57",
    "64",
    "61",
    "65",
    "63",
    "58A",
    "58B",
    "K5",
    "манёвр → исход",
)


def test_integration_map_covers_modules() -> None:
    text = MAP.read_text(encoding="utf-8")
    missing = [name for name in REQUIRED if name not in text]
    assert missing == []
    assert "pretrade_check/service.py" in text
    assert "fund_report/metrics.py" in text
    assert "analyze_decisions" in text
