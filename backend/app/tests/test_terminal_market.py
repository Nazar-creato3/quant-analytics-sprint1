"""Tests for Terminal Market aggregate — snapshot shape, no-zero-fake, market hours."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.services.terminal_platform.market.hours import (
    build_market_hours,
    session_status_for_exchange,
)
from app.services.terminal_platform.market.pulse import compute_fear_greed, fear_greed_label
from app.services.terminal_platform.market.quotes import fetch_quote_safe
from app.services.terminal_platform.market.schemas import (
    IndexQuoteRow,
    MoverRow,
    TerminalMarketSnapshot,
)
from app.services.terminal_platform.market.snapshot import _build_performance
from app.services.terminal_platform.models import FetchResult


class TestMarketHours:
    def test_nyse_open_midweek(self) -> None:
        now = datetime(2026, 7, 29, 15, 0, tzinfo=timezone.utc)
        assert session_status_for_exchange("NYSE", now) == "open"

    def test_nyse_pre_market(self) -> None:
        now = datetime(2026, 7, 29, 10, 0, tzinfo=timezone.utc)
        assert session_status_for_exchange("NYSE", now) == "pre"

    def test_nyse_weekend_closed(self) -> None:
        now = datetime(2026, 8, 1, 15, 0, tzinfo=timezone.utc)
        assert session_status_for_exchange("NYSE", now) == "closed"

    def test_moex_open(self) -> None:
        now = datetime(2026, 7, 29, 7, 30, tzinfo=timezone.utc)
        assert session_status_for_exchange("MOEX", now) == "open"

    def test_tse_lunch_closed(self) -> None:
        now = datetime(2026, 7, 29, 3, 0, tzinfo=timezone.utc)
        assert session_status_for_exchange("TSE", now) == "closed"

    def test_build_market_hours_shape(self) -> None:
        rows = build_market_hours(datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc))
        exchanges = {r.exchange for r in rows}
        assert {"NYSE", "NASDAQ", "LSE", "TSE", "SSE", "NSE", "MOEX"} <= exchanges
        for r in rows:
            assert r.status in {"open", "closed", "pre", "post", "holiday"}
            assert r.local_time
            assert r.next_event
            assert r.next_event_at


class TestNoZeroFake:
    @pytest.mark.asyncio
    async def test_failed_quote_is_no_data_not_zero(self) -> None:
        failed = FetchResult(
            success=False,
            error="timeout",
            error_code="TIMEOUT",
            provider="yfinance",
        )
        with patch(
            "app.services.terminal_platform.market.quotes.get_terminal_router"
        ) as mock_factory:
            mock_factory.return_value.get_quote = AsyncMock(return_value=failed)
            out = await fetch_quote_safe("^GSPC")
        assert out["status"] == "no_data"
        assert out.get("price") != 0

    @pytest.mark.asyncio
    async def test_missing_price_is_no_data(self) -> None:
        none_price = FetchResult(
            success=True,
            data={"symbol": "^GSPC", "price": None, "provider": "yfinance"},
            provider="yfinance",
        )
        with patch(
            "app.services.terminal_platform.market.quotes.get_terminal_router"
        ) as mock_factory:
            mock_factory.return_value.get_quote = AsyncMock(return_value=none_price)
            out = await fetch_quote_safe("^GSPC")
        assert out["status"] == "no_data"
        assert out.get("reason") == "missing_price"

    def test_performance_omits_fake_zeros(self) -> None:
        indices = {
            "SPX": IndexQuoteRow(symbol="SPX", status="no_data", reason="timeout"),
            "VIX": IndexQuoteRow(symbol="VIX", status="ok", price=14.2, change_pct=-1.1),
        }
        rows = _build_performance(indices, [])
        spx_rows = [r for r in rows if r.label == "S&P 500 Daily" and r.period == "TODAY"]
        assert spx_rows
        assert spx_rows[0].status == "no_data"
        assert spx_rows[0].value is None
        vix_rows = [r for r in rows if r.label == "VIX"]
        assert vix_rows[0].status == "ok"
        assert vix_rows[0].value == 14.2


class TestFearGreed:
    def test_formula_vix_only(self) -> None:
        score, comps = compute_fear_greed(vix=12.0, advancers=None, decliners=None, momentum_pcts=[])
        assert score is not None
        assert score >= 90
        assert "vix" in comps
        assert fear_greed_label(score) in {"Greed", "Extreme Greed"}

    def test_insufficient(self) -> None:
        score, comps = compute_fear_greed(
            vix=None, advancers=None, decliners=None, momentum_pcts=[]
        )
        assert score is None
        assert "note" in comps


class TestVixChangeUnification:
    def test_resolve_change_pct_prefers_batch(self) -> None:
        from app.services.terminal_platform.market.quotes import resolve_change_pct

        assert resolve_change_pct(-3.8, 0.4) == 0.4
        assert resolve_change_pct(None, 0.4) == 0.4
        assert resolve_change_pct(-3.8, None) == -3.8


class TestTapeDedupe:
    def test_build_tape_dedupes_symbols(self) -> None:
        from app.services.terminal_platform.market.coverage import build_tape_items
        from app.services.terminal_platform.market.schemas import (
            IndexQuoteRow,
            MarketPulseBlock,
            WatchlistEnrichedRow,
        )

        indices = [
            IndexQuoteRow(symbol="IMOEX", price=2800.0, change_pct=0.3, status="ok"),
            IndexQuoteRow(symbol="VIX", price=15.2, change_pct=0.4, status="ok"),
        ]
        watch = [
            WatchlistEnrichedRow(symbol="IMOEX", display="IMOEX", last=2800.0, change_pct=0.3, status="ok"),
        ]
        tape = build_tape_items(
            indices=indices,
            watchlist=watch,
            pulse=MarketPulseBlock(),
            hours=[],
            news=[],
        )
        symbols = [t.symbol for t in tape if t.symbol]
        assert symbols.count("IMOEX") == 1
        assert symbols.count("VIX") == 1


class TestBatchChangeMerge:
    @pytest.mark.asyncio
    async def test_fetch_indices_fills_change_pct_from_batch(self) -> None:
        from app.services.terminal_platform.market.quotes import INDEX_UNIVERSE, fetch_indices

        live = IndexQuoteRow(
            symbol="SPX",
            name="S&P 500",
            api_symbol="^GSPC",
            price=5000.0,
            change=None,
            change_pct=None,
            status="ok",
            provider="yfinance",
        )
        stubs = [live] + [
            IndexQuoteRow(symbol=ui, status="no_data", reason="x")
            for ui, *_ in INDEX_UNIVERSE[1:]
        ]
        batch = {
            "^GSPC": {
                "status": "ok",
                "price": 5000.0,
                "change_pct": 1.25,
                "change": 62.5,
                "week_change_pct": 2.0,
                "month_change_pct": -0.5,
                "provider": "yfinance_batch",
            }
        }
        with (
            patch(
                "app.services.terminal_platform.market.quotes.enrich_index_row",
                new_callable=AsyncMock,
                side_effect=stubs,
            ),
            patch(
                "app.services.terminal_platform.market.batch_enrich.enrich_change_map",
                new_callable=AsyncMock,
                return_value=batch,
            ),
        ):
            rows = await fetch_indices(include_periods=True)
        spx = next(r for r in rows if r.symbol == "SPX")
        assert spx.change_pct == 1.25
        assert spx.change == 62.5
        assert spx.week_change_pct == 2.0


class TestSnapshotShape:
    @pytest.mark.asyncio
    async def test_snapshot_keys(self) -> None:
        from app.services.terminal_platform.market.schemas import (
            MarketPulseBlock,
            PortfolioSummaryBlock,
        )
        from app.services.terminal_platform.market.snapshot import build_terminal_snapshot

        with (
            patch(
                "app.services.terminal_platform.market.snapshot.fetch_indices",
                new_callable=AsyncMock,
                return_value=[
                    IndexQuoteRow(
                        symbol="SPX",
                        name="S&P 500",
                        price=5000.0,
                        change=10.0,
                        change_pct=0.2,
                        status="ok",
                        provider="yfinance",
                    ),
                    IndexQuoteRow(symbol="NDX", status="no_data", reason="failed"),
                ],
            ),
            patch(
                "app.services.terminal_platform.market.snapshot.build_enriched_watchlist",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "app.services.terminal_platform.market.snapshot.build_portfolio_summary",
                new_callable=AsyncMock,
                return_value=PortfolioSummaryBlock(has_positions=False, message="empty"),
            ),
            patch(
                "app.services.terminal_platform.market.snapshot.build_pulse",
                new_callable=AsyncMock,
                return_value=MarketPulseBlock(
                    fear_greed=50,
                    label="Neutral",
                    gainers=[MoverRow(symbol="NVDA", change_pct=3.1)],
                ),
            ),
            patch(
                "app.services.terminal_platform.market.snapshot._fetch_news",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "app.services.terminal_platform.market.snapshot._fetch_calendar",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            snap = await build_terminal_snapshot(db=None, email=None)

        assert isinstance(snap, TerminalMarketSnapshot)
        payload = snap.model_dump(mode="json")
        for key in (
            "as_of",
            "indices",
            "performance",
            "pulse",
            "watchlist_enriched",
            "portfolio_summary",
            "market_hours",
            "tape_items",
            "news",
            "calendar",
            "quant_factors",
            "data_coverage",
        ):
            assert key in payload
        ndx = next(i for i in snap.indices if i.symbol == "NDX")
        assert ndx.status == "no_data"
        assert ndx.price is None
