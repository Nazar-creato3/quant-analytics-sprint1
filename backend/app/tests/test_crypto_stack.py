"""Smoke tests for crypto_stack service (no network required for health)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.crypto_stack.health import stack_health
from app.services.crypto_stack.market import ta_snapshot


def test_stack_health_shape():
    result = stack_health()
    assert "packages" in result
    assert "available_count" in result
    assert isinstance(result["packages"], list)
    assert len(result["packages"]) >= 3
    names = {p["name"] for p in result["packages"]}
    assert "ccxt" in names


def test_ta_snapshot_with_mocked_ohlcv():
    candles = [
        {"ts": i * 3600_000, "open": 100 + i, "high": 110 + i, "low": 90 + i, "close": 105 + i, "volume": 1.0}
        for i in range(40)
    ]
    with patch(
        "app.services.crypto_stack.market.fetch_ohlcv",
        return_value={"candles": candles, "fetched_at": "2026-01-01T00:00:00Z"},
    ):
        snap = ta_snapshot("BTC/USDT", "1h", 40)
    assert snap["ok"] is True
    assert snap["last"] == candles[-1]["close"]
    assert "sma20" in snap


def test_crypto_stack_router_registered():
    """Router module defines expected paths without importing the full app graph."""
    import ast
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "api" / "v1" / "endpoints" / "crypto_stack.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    routes: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in {"get", "post", "put", "delete"} and node.args:
                arg0 = node.args[0]
                if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
                    routes.append(arg0.value)
    assert "/health" in routes
    assert "/ticker" in routes
    assert "/ohlcv" in routes
    assert "/ta" in routes
