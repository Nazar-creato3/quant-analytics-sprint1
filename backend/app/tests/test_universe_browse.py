from unittest.mock import patch

import pytest

from app.services.market_data.universe_search import search_universe


@pytest.mark.asyncio
async def test_empty_query_browses_forex():
    with patch(
        "app.services.market_data.universe_search._load_moex_board_rows",
        return_value=[],
    ):
        hits = await search_universe("", limit=20, category="fx", region="all")
    symbols = [h.symbol for h in hits]
    assert "EUR/USD" in symbols


@pytest.mark.asyncio
async def test_empty_query_browses_europe_equities():
    with patch(
        "app.services.market_data.universe_search._load_moex_board_rows",
        return_value=[],
    ):
        hits = await search_universe("", limit=20, category="equities", region="europe")
    assert any(h.region == "europe" for h in hits)
    assert any(h.symbol.endswith(".L") or h.symbol.endswith(".XETRA") for h in hits)
