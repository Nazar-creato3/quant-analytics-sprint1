"""GA16-079: portfolio summary must not send exception text to the client."""
from __future__ import annotations

import pytest

from app.services.terminal_platform.market.portfolio_block import build_portfolio_summary


@pytest.mark.asyncio
async def test_portfolio_summary_hides_exception(monkeypatch) -> None:
    async def boom(*_a, **_k):
        raise RuntimeError("secret-table-xyz")

    monkeypatch.setattr("app.services.portfolio.metrics.build_portfolio_metrics", boom)
    out = await build_portfolio_summary(db=object(), email="a@b.c")  # type: ignore[arg-type]
    assert out.has_positions is False
    assert "secret-table-xyz" not in (out.message or "")
    assert out.message == "нет данных"
