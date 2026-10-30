"""Tests for StrategyMesh, regime adapters, and all built-in strategies."""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.domain.deal_intent_enums import DealIntentDirection, DealIntentStatus
from app.domain.enums import AssetCategory, Strategy
from app.services.strategy import (
    BreakoutStrategy,
    CryptoRegimeAdapter,
    EquityRegimeAdapter,
    GridMode,
    GridStrategy,
    HedgeStrategy,
    IncomeStrategy,
    InstrumentSnapshot,
    MarketRegime,
    MeanReversionStrategy,
    RawMarketSnapshot,
    RotationStrategy,
    SleeveStrategyContext,
    StrategyMesh,
    StrategyRegistrationError,
    TrendStrategy,
    VolatilityHarvestingStrategy,
)


def _instrument(
    instrument_id: int,
    symbol: str,
    category: AssetCategory,
    price: str,
    **kwargs: object,
) -> InstrumentSnapshot:
    defaults = {
        "volatility": 0.12,
        "spread_bps": 8.0,
        "momentum": 0.0,
        "mean_reversion_z": 0.0,
        "breakout_strength": 0.0,
        "yield_pct": 0.0,
        "relative_strength": 0.0,
    }
    defaults.update(kwargs)
    return InstrumentSnapshot(
        instrument_id=instrument_id,
        symbol=symbol,
        category=category,
        last_price=Decimal(price),
        volatility=float(defaults["volatility"]),
        spread_bps=float(defaults["spread_bps"]),
        momentum=float(defaults["momentum"]),
        mean_reversion_z=float(defaults["mean_reversion_z"]),
        breakout_strength=float(defaults["breakout_strength"]),
        yield_pct=float(defaults["yield_pct"]),
        relative_strength=float(defaults["relative_strength"]),
    )


def _sleeve(
    category: AssetCategory,
    instruments: tuple[InstrumentSnapshot, ...],
    *,
    sleeve_id: str = "sleeve-1",
) -> SleeveStrategyContext:
    return SleeveStrategyContext(
        sleeve_id=sleeve_id,
        category=category,
        instruments=instruments,
        risk_budget_remaining=Decimal("5000"),
    )


def _crypto_context(
    category: AssetCategory,
    instruments: tuple[InstrumentSnapshot, ...],
    *,
    grid_mode: GridMode = GridMode.POINT,
    regime: MarketRegime | None = None,
) -> object:
    sleeve = _sleeve(category, instruments)
    raw = RawMarketSnapshot(
        instruments=instruments,
        session_active=True,
        bid_ask_imbalance=0.2,
    )
    adapter = CryptoRegimeAdapter()
    ctx = adapter.build_context(raw, sleeve)
    if regime is not None:
        return _replace_regime(ctx, regime, grid_mode)
    if grid_mode != GridMode.POINT:
        return _replace_regime(ctx, ctx.regime, grid_mode)
    return ctx


def _equity_context(
    category: AssetCategory,
    instruments: tuple[InstrumentSnapshot, ...],
    *,
    session_active: bool = True,
    vix: float | None = 20.0,
    regime: MarketRegime | None = None,
    grid_mode: GridMode = GridMode.POINT,
) -> object:
    sleeve = _sleeve(category, instruments)
    raw = RawMarketSnapshot(
        instruments=instruments,
        session_active=session_active,
        vix_level=vix,
    )
    adapter = EquityRegimeAdapter()
    ctx = adapter.build_context(raw, sleeve)
    if regime is not None:
        return _replace_regime(ctx, regime, grid_mode)
    if grid_mode != GridMode.POINT:
        return _replace_regime(ctx, ctx.regime, grid_mode)
    return ctx


def _replace_regime(ctx, regime: MarketRegime, grid_mode: GridMode):
    from app.services.strategy.types import StrategyMarketContext

    return StrategyMarketContext(
        sleeve=ctx.sleeve,
        regime=regime,
        session_active=ctx.session_active,
        microstructure_score=ctx.microstructure_score,
        volatility_percentile=ctx.volatility_percentile,
        asset_class=ctx.asset_class,
        grid_mode=grid_mode,
        news_locked_instrument_ids=ctx.news_locked_instrument_ids,
    )


def _assert_draft_intent(intent, *, strategy: Strategy, sleeve_id: str, instrument_id: int):
    assert intent is not None
    assert intent.status == DealIntentStatus.DRAFT
    assert intent.strategy == strategy
    assert intent.sleeve_id == sleeve_id
    assert intent.instrument_id == instrument_id


class TestStrategyMesh:
    def test_default_registers_all_eight(self):
        mesh = StrategyMesh.default()
        assert len(mesh) == 8
        for strategy_type in Strategy:
            assert strategy_type in mesh

    def test_duplicate_registration_raises(self):
        mesh = StrategyMesh.default()
        with pytest.raises(StrategyRegistrationError):
            mesh.register(GridStrategy())

    def test_analyze_unknown_strategy_returns_none(self):
        mesh = StrategyMesh()
        ctx = _crypto_context(
            AssetCategory.CRYPTO,
            (_instrument(1, "BTCUSDT", AssetCategory.CRYPTO, "50000"),),
            regime=MarketRegime.RANGE,
        )
        assert mesh.analyze(Strategy.GRID, ctx) is None


class TestRegimeAdapters:
    def test_crypto_adapter_always_session_active(self):
        inst = _instrument(1, "ETHUSDT", AssetCategory.CRYPTO, "3000", volatility=0.2)
        ctx = _crypto_context(AssetCategory.CRYPTO, (inst,))
        assert ctx.asset_class == "crypto"
        assert ctx.session_active is True
        assert ctx.microstructure_score > 0

    def test_equity_adapter_respects_session(self):
        inst = _instrument(2, "AAPL", AssetCategory.EQUITIES, "180")
        ctx = _equity_context(AssetCategory.EQUITIES, (inst,), session_active=False)
        assert ctx.asset_class == "equity"
        assert ctx.session_active is False

    def test_equity_high_vix_maps_to_high_vol_regime(self):
        inst = _instrument(2, "SPY", AssetCategory.ETF, "450", momentum=0.0, volatility=0.1)
        ctx = _equity_context(AssetCategory.ETF, (inst,), vix=30.0)
        assert ctx.regime == MarketRegime.HIGH_VOL


class TestGridStrategy:
    @pytest.mark.parametrize("adapter_fn", [_crypto_context, _equity_context])
    def test_point_mode_single_instrument(self, adapter_fn):
        inst = _instrument(10, "BTCUSDT", AssetCategory.CRYPTO, "42000", volatility=0.1)
        category = AssetCategory.CRYPTO if adapter_fn is _crypto_context else AssetCategory.SPECULATIVE_SLEEVE
        if adapter_fn is _equity_context:
            inst = _instrument(10, "MSTR", AssetCategory.SPECULATIVE_SLEEVE, "420", volatility=0.1)
        ctx = adapter_fn(category, (inst,), regime=MarketRegime.RANGE, grid_mode=GridMode.POINT)

        intent = GridStrategy().analyze(ctx)
        _assert_draft_intent(intent, strategy=Strategy.GRID, sleeve_id="sleeve-1", instrument_id=10)
        assert intent.exit_logic.get("grid_mode") == GridMode.POINT.value

    @pytest.mark.parametrize("adapter_fn", [_crypto_context, _equity_context])
    def test_diversified_mode_multiple_instruments(self, adapter_fn):
        instruments = (
            _instrument(11, "BTCUSDT", AssetCategory.CRYPTO, "42000", volatility=0.1),
            _instrument(12, "ETHUSDT", AssetCategory.CRYPTO, "3000", volatility=0.09),
        )
        category = AssetCategory.CRYPTO
        if adapter_fn is _equity_context:
            category = AssetCategory.SPECULATIVE_SLEEVE
            instruments = (
                _instrument(11, "COIN", AssetCategory.SPECULATIVE_SLEEVE, "200", volatility=0.1),
                _instrument(12, "MARA", AssetCategory.SPECULATIVE_SLEEVE, "18", volatility=0.09),
            )

        ctx = adapter_fn(
            category,
            instruments,
            regime=MarketRegime.RANGE,
            grid_mode=GridMode.DIVERSIFIED,
        )
        strategy = GridStrategy()
        intents = strategy.analyze_diversified(ctx)

        assert len(intents) == 2
        for intent in intents:
            assert intent.status == DealIntentStatus.DRAFT
            assert intent.strategy == Strategy.GRID
            assert intent.exit_logic.get("grid_mode") == GridMode.DIVERSIFIED.value

    def test_point_mode_rejects_multiple_instruments(self):
        instruments = (
            _instrument(11, "BTCUSDT", AssetCategory.CRYPTO, "42000", volatility=0.1),
            _instrument(12, "ETHUSDT", AssetCategory.CRYPTO, "3000", volatility=0.09),
        )
        ctx = _crypto_context(
            AssetCategory.CRYPTO,
            instruments,
            regime=MarketRegime.RANGE,
            grid_mode=GridMode.POINT,
        )
        assert GridStrategy().analyze(ctx) is None

    def test_blocks_wrong_sleeve_category(self):
        inst = _instrument(1, "AAPL", AssetCategory.EQUITIES, "180")
        ctx = _equity_context(AssetCategory.EQUITIES, (inst,), regime=MarketRegime.RANGE)
        assert GridStrategy().analyze(ctx) is None


class TestTrendStrategy:
    @pytest.mark.parametrize("adapter_fn", [_crypto_context, _equity_context])
    def test_trend_up_long(self, adapter_fn):
        category = AssetCategory.CRYPTO if adapter_fn is _crypto_context else AssetCategory.EQUITIES
        symbol = "BTCUSDT" if adapter_fn is _crypto_context else "AAPL"
        inst = _instrument(20, symbol, category, "100", momentum=0.25)
        ctx = adapter_fn(category, (inst,), regime=MarketRegime.TREND_UP)

        intent = TrendStrategy().analyze(ctx)
        _assert_draft_intent(intent, strategy=Strategy.TREND, sleeve_id="sleeve-1", instrument_id=20)
        assert intent.direction == DealIntentDirection.LONG

    @pytest.mark.parametrize("adapter_fn", [_crypto_context, _equity_context])
    def test_trend_down_short(self, adapter_fn):
        category = AssetCategory.CRYPTO if adapter_fn is _crypto_context else AssetCategory.ETF
        symbol = "SOLUSDT" if adapter_fn is _crypto_context else "QQQ"
        inst = _instrument(21, symbol, category, "100", momentum=-0.22)
        ctx = adapter_fn(category, (inst,), regime=MarketRegime.TREND_DOWN)

        intent = TrendStrategy().analyze(ctx)
        _assert_draft_intent(intent, strategy=Strategy.TREND, sleeve_id="sleeve-1", instrument_id=21)
        assert intent.direction == DealIntentDirection.SHORT


class TestMeanReversionStrategy:
    @pytest.mark.parametrize("adapter_fn", [_crypto_context, _equity_context])
    def test_oversold_long(self, adapter_fn):
        category = AssetCategory.CRYPTO if adapter_fn is _crypto_context else AssetCategory.EQUITIES
        symbol = "ADAUSDT" if adapter_fn is _crypto_context else "MSFT"
        inst = _instrument(30, symbol, category, "50", mean_reversion_z=-2.1)
        ctx = adapter_fn(category, (inst,), regime=MarketRegime.RANGE)

        intent = MeanReversionStrategy().analyze(ctx)
        _assert_draft_intent(
            intent,
            strategy=Strategy.MEAN_REVERSION,
            sleeve_id="sleeve-1",
            instrument_id=30,
        )
        assert intent.direction == DealIntentDirection.LONG

    @pytest.mark.parametrize("adapter_fn", [_crypto_context, _equity_context])
    def test_overbought_short(self, adapter_fn):
        category = AssetCategory.FX if adapter_fn is _crypto_context else AssetCategory.ETF
        symbol = "EURUSDT" if adapter_fn is _crypto_context else "IWM"
        inst = _instrument(31, symbol, category, "1.10", mean_reversion_z=2.0)
        ctx = adapter_fn(category, (inst,), regime=MarketRegime.HIGH_VOL)

        intent = MeanReversionStrategy().analyze(ctx)
        _assert_draft_intent(
            intent,
            strategy=Strategy.MEAN_REVERSION,
            sleeve_id="sleeve-1",
            instrument_id=31,
        )
        assert intent.direction == DealIntentDirection.SHORT


class TestBreakoutStrategy:
    @pytest.mark.parametrize("adapter_fn", [_crypto_context, _equity_context])
    def test_breakout_long(self, adapter_fn):
        category = AssetCategory.CRYPTO if adapter_fn is _crypto_context else AssetCategory.EQUITIES
        symbol = "DOGEUSDT" if adapter_fn is _crypto_context else "NVDA"
        inst = _instrument(40, symbol, category, "0.15", breakout_strength=0.85)
        ctx = adapter_fn(category, (inst,), regime=MarketRegime.TREND_UP)

        intent = BreakoutStrategy().analyze(ctx)
        _assert_draft_intent(intent, strategy=Strategy.BREAKOUT, sleeve_id="sleeve-1", instrument_id=40)
        assert intent.direction == DealIntentDirection.LONG


class TestHedgeStrategy:
    @pytest.mark.parametrize("adapter_fn", [_crypto_context, _equity_context])
    def test_high_vol_hedge(self, adapter_fn):
        category = (
            AssetCategory.MACRO_HEDGE if adapter_fn is _crypto_context else AssetCategory.DEFENSIVE_SLEEVE
        )
        symbol = "BTCUSD_PERP" if adapter_fn is _crypto_context else "TLT"
        inst = _instrument(50, symbol, category, "95", momentum=-0.05)
        ctx = adapter_fn(category, (inst,), regime=MarketRegime.HIGH_VOL)

        intent = HedgeStrategy().analyze(ctx)
        _assert_draft_intent(intent, strategy=Strategy.HEDGE, sleeve_id="sleeve-1", instrument_id=50)


class TestIncomeStrategy:
    @pytest.mark.parametrize("adapter_fn", [_crypto_context, _equity_context])
    def test_yield_picker(self, adapter_fn):
        category = AssetCategory.INCOME_SLEEVE if adapter_fn is _crypto_context else AssetCategory.RATES_BONDS
        symbol = "STETH" if adapter_fn is _crypto_context else "BND"
        inst = _instrument(60, symbol, category, "100", yield_pct=4.5)
        ctx = adapter_fn(category, (inst,), regime=MarketRegime.RANGE)

        intent = IncomeStrategy().analyze(ctx)
        _assert_draft_intent(intent, strategy=Strategy.INCOME, sleeve_id="sleeve-1", instrument_id=60)


class TestRotationStrategy:
    @pytest.mark.parametrize("adapter_fn", [_crypto_context, _equity_context])
    def test_sector_leader(self, adapter_fn):
        category = (
            AssetCategory.THEMATIC_BASKET if adapter_fn is _crypto_context else AssetCategory.SECTOR_BASKET
        )
        instruments = (
            _instrument(70, "AI_BASKET", category, "100", relative_strength=0.02),
            _instrument(71, "DEFI_BASKET", category, "50", relative_strength=0.12),
        )
        ctx = adapter_fn(category, instruments, regime=MarketRegime.TREND_UP)

        intent = RotationStrategy().analyze(ctx)
        _assert_draft_intent(intent, strategy=Strategy.ROTATION, sleeve_id="sleeve-1", instrument_id=71)


class TestVolatilityHarvestingStrategy:
    @pytest.mark.parametrize("adapter_fn", [_crypto_context, _equity_context])
    def test_high_vol_harvest(self, adapter_fn):
        category = AssetCategory.CRYPTO if adapter_fn is _crypto_context else AssetCategory.FX
        symbol = "BTCUSDT" if adapter_fn is _crypto_context else "EURUSD"
        inst = _instrument(80, symbol, category, "100", volatility=0.35)
        ctx = adapter_fn(category, (inst,), regime=MarketRegime.HIGH_VOL)
        from app.services.strategy.types import StrategyMarketContext

        ctx = StrategyMarketContext(
            sleeve=ctx.sleeve,
            regime=ctx.regime,
            session_active=ctx.session_active,
            microstructure_score=ctx.microstructure_score,
            volatility_percentile=0.75,
            asset_class=ctx.asset_class,
        )

        intent = VolatilityHarvestingStrategy().analyze(ctx)
        _assert_draft_intent(
            intent,
            strategy=Strategy.VOLATILITY_HARVESTING,
            sleeve_id="sleeve-1",
            instrument_id=80,
        )


class TestSleeveScopeOnly:
    def test_strategy_never_sees_other_sleeve_instruments(self):
        """Instruments outside sleeve category are filtered by adapters."""
        inst = _instrument(1, "AAPL", AssetCategory.EQUITIES, "180", momentum=0.3)
        sleeve = _sleeve(AssetCategory.CRYPTO, (inst,))
        raw = RawMarketSnapshot(instruments=(inst,), session_active=True)
        ctx = CryptoRegimeAdapter().build_context(raw, sleeve)

        assert len(ctx.sleeve.instruments) == 0
        assert TrendStrategy().analyze(_replace_regime(ctx, MarketRegime.TREND_UP, GridMode.POINT)) is None

    def test_equity_blocks_when_session_closed(self):
        inst = _instrument(2, "AAPL", AssetCategory.EQUITIES, "180", momentum=0.3)
        ctx = _equity_context(AssetCategory.EQUITIES, (inst,), session_active=False, regime=MarketRegime.TREND_UP)
        assert TrendStrategy().analyze(ctx) is None

    def test_mesh_analyze_all_returns_draft_only(self):
        mesh = StrategyMesh.default()
        inst = _instrument(1, "BTCUSDT", AssetCategory.CRYPTO, "42000", volatility=0.1)
        ctx = _crypto_context(AssetCategory.CRYPTO, (inst,), regime=MarketRegime.RANGE)
        results = mesh.analyze_all(ctx)
        for intent in results.values():
            if intent is not None:
                assert intent.status == DealIntentStatus.DRAFT
