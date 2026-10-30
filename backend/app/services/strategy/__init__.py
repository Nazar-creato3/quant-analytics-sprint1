"""Strategy package — lazy exports to avoid heavy import chains in unit tests."""

from __future__ import annotations

from typing import Any

_LAZY: dict[str, tuple[str, str]] = {
    "BaseStrategy": ("app.services.strategy.base", "BaseStrategy"),
    "IStrategy": ("app.services.strategy.interface", "IStrategy"),
    "StrategyIntentProposal": ("app.services.strategy.mesh", "StrategyIntentProposal"),
    "StrategyMesh": ("app.services.strategy.mesh", "StrategyMesh"),
    "StrategyRegistrationError": ("app.services.strategy.mesh", "StrategyRegistrationError"),
    "CryptoRegimeAdapter": ("app.services.strategy.regime", "CryptoRegimeAdapter"),
    "EquityRegimeAdapter": ("app.services.strategy.regime", "EquityRegimeAdapter"),
    "RegimeAdapter": ("app.services.strategy.regime", "RegimeAdapter"),
    "BreakoutStrategy": ("app.services.strategy.strategies", "BreakoutStrategy"),
    "GridStrategy": ("app.services.strategy.strategies", "GridStrategy"),
    "HedgeStrategy": ("app.services.strategy.strategies", "HedgeStrategy"),
    "IncomeStrategy": ("app.services.strategy.strategies", "IncomeStrategy"),
    "MeanReversionStrategy": ("app.services.strategy.strategies", "MeanReversionStrategy"),
    "RotationStrategy": ("app.services.strategy.strategies", "RotationStrategy"),
    "TrendStrategy": ("app.services.strategy.strategies", "TrendStrategy"),
    "VolatilityHarvestingStrategy": ("app.services.strategy.strategies", "VolatilityHarvestingStrategy"),
    "GridMode": ("app.services.strategy.types", "GridMode"),
    "InstrumentSnapshot": ("app.services.strategy.types", "InstrumentSnapshot"),
    "MarketRegime": ("app.services.strategy.types", "MarketRegime"),
    "RawMarketSnapshot": ("app.services.strategy.types", "RawMarketSnapshot"),
    "SleeveStrategyContext": ("app.services.strategy.types", "SleeveStrategyContext"),
    "StrategyMarketContext": ("app.services.strategy.types", "StrategyMarketContext"),
}

__all__ = list(_LAZY.keys())


def __getattr__(name: str) -> Any:
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_path, attr = target
    import importlib

    module = importlib.import_module(module_path)
    return getattr(module, attr)
