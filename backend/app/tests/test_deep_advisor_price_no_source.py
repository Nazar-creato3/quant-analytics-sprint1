"""GA16-305: price reply must not name source or market data."""

from pathlib import Path


def test_price_branch_has_no_source_or_market_data():
    text = Path("app/services/chat/deep_advisor.py").read_text(encoding="utf-8")
    # Narrow to the price subtype block after dividend returns.
    start = text.index('if subtype == "price":')
    end = text.index('if subtype == "volume":', start)
    block = text[start:end]
    assert "источник" not in block
    assert "market data" not in block
    assert "source" not in block
