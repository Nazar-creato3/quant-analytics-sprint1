"""GA16-353: missing sector context message must be Russian."""

from pathlib import Path


def test_sector_missing_message_russian():
    text = Path("app/api/v1/endpoints/market_graph.py").read_text(encoding="utf-8")
    assert "Sector context not found" not in text
    assert "секторный контекст пока недоступен" in text
