"""Trading engine adapters — one per GitHub repo (Backtrader intentionally excluded)."""
from __future__ import annotations

from typing import Any

from app.services.trading_engines.base import EngineAdapter
from app.services.trading_engines.engines.ccxt_engine import CcxtEngine
from app.services.trading_engines.engines.finrl_engine import FinrlEngine
from app.services.trading_engines.engines.freqtrade_engine import FreqtradeEngine
from app.services.trading_engines.engines.hummingbot_engine import HummingbotEngine
from app.services.trading_engines.engines.lumibot_engine import LumibotEngine
from app.services.trading_engines.engines.nautilus_engine import NautilusEngine
from app.services.trading_engines.engines.tradingagents_engine import TradingAgentsEngine
from app.services.trading_engines.engines.vectorbt_engine import VectorbtEngine

_REGISTRY: dict[str, EngineAdapter] = {
    CcxtEngine.name: CcxtEngine(),
    VectorbtEngine.name: VectorbtEngine(),
    NautilusEngine.name: NautilusEngine(),
    FreqtradeEngine.name: FreqtradeEngine(),
    HummingbotEngine.name: HummingbotEngine(),
    TradingAgentsEngine.name: TradingAgentsEngine(),
    FinrlEngine.name: FinrlEngine(),
    LumibotEngine.name: LumibotEngine(),
}

ENGINE_NAMES: tuple[str, ...] = tuple(_REGISTRY.keys())


def get_engine(name: str) -> EngineAdapter | None:
    return _REGISTRY.get(name)


def list_engines() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for name in ENGINE_NAMES:
        adapter = _REGISTRY[name]
        try:
            payload = adapter.status()
        except Exception as exc:  # noqa: BLE001
            payload = {
                "name": name,
                "installed": False,
                "runnable": False,
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
        out.append(payload)
    return out
