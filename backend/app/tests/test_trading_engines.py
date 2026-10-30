"""Tests for trading-engine registry and health (no network)."""
from __future__ import annotations

import pytest

from app.services.risk.maneuver_debate import debate_maneuvers_dry_run
from app.services.trading_engines.health import engines_health, mcp_health
from app.services.trading_engines.registry import ENGINE_NAMES, get_engine, list_engines
from app.services.trading_engines.grid.freqtrade_bridge import read_signal_state, write_signal_state


EXPECTED = {
    "ccxt",
    "vectorbt",
    "nautilus-trader",
    "freqtrade",
    "hummingbot",
    "tradingagents",
    "finrl",
    "lumibot",
}


def test_registry_has_eight_engines():
    assert set(ENGINE_NAMES) == EXPECTED
    assert len(ENGINE_NAMES) == 8
    for name in EXPECTED:
        assert get_engine(name) is not None


def test_list_engines_shape():
    items = list_engines()
    assert len(items) == 8
    for item in items:
        assert "name" in item
        assert "module" in item
        assert "integration_mode" in item
        assert "installed" in item
        assert "runnable" in item


def test_engines_health_aggregate():
    payload = engines_health(github_check=False)
    assert payload["engine_count"] == 8
    assert len(payload["engines"]) == 8
    assert "mcp" in payload
    assert "github" in payload
    assert "alpaca_data" in payload
    assert payload["alpaca_data"]["quotes_only"] is True
    assert payload["alpaca_data"]["live_orders"] is False


def test_mcp_health_shape():
    mcp = mcp_health()
    assert "servers" in mcp
    assert isinstance(mcp["servers"], list)
    names = {s["name"] for s in mcp["servers"]}
    assert "binance_context_server" in names


def test_ccxt_engine_status():
    adapter = get_engine("ccxt")
    st = adapter.status()
    assert st["name"] == "ccxt"
    assert st["module"] == "data_layer"
    assert st["integration_mode"] == "pip_dependency"


def test_freqtrade_sidecar_infra_files_exist():
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    assert (root / "infra" / "freqtrade" / "docker-compose.yml").is_file()
    assert (root / "infra" / "freqtrade" / "user_data" / "config.dryrun.json").is_file()
    assert (root / "infra" / "freqtrade" / "strategies" / "ApexSignalBridge.py").is_file()
    assert (root / "scripts" / "start-freqtrade-sidecar.ps1").is_file()


def test_freqtrade_signal_bridge(tmp_path, monkeypatch: pytest.MonkeyPatch):
    signal_file = tmp_path / "signal.json"
    monkeypatch.setenv("FREQTRADE_SIGNAL_PATH", str(signal_file))
    path = write_signal_state({"symbol": "ETH/USDT", "direction": "long", "target_weight": 0.05})
    assert path.is_file()
    state = read_signal_state()
    assert state["symbol"] == "ETH/USDT"
    assert state["schema_version"] == 1


def test_debate_dry_run():
    candidates = [
        {"ticker": "AAPL", "direction": "long", "confidence": 0.72, "rationale": "mom"},
        {"ticker": "XYZ", "direction": "short", "confidence": 0.40, "rationale": "weak"},
    ]
    result = debate_maneuvers_dry_run(candidates)
    assert result["ok"] is True
    assert result["approved_count"] >= 1


def test_health_excludes_backtrader_and_alpaca_bridge():
    payload = engines_health(github_check=False)
    excluded = payload.get("excluded") or {}
    assert "backtrader" in excluded
    assert "alpaca-backtrader-api" in excluded


def test_event_sma_and_grid_and_finrl_actions():
    from app.services.trading_engines.runtime.event_backtest import run_event_sma_backtest
    from app.services.trading_engines.runtime.finrl_policy import policy_score
    from app.services.trading_engines.runtime.grid_plan import propose_grid

    prices = [100.0 + i * 0.2 for i in range(60)]
    ev = run_event_sma_backtest(prices)
    assert ev["bars"] == 60
    assert ev["n_trades"] >= 0

    fin = policy_score(prices)
    assert fin["ok"] is True
    assert fin["mode"] in {"excess_return_heuristic", "trained_q_learning", "trained_ppo"}
    assert fin["direction"] in (-1, 0, 1)

    grid = propose_grid(symbol="BTC-USD", mid=65000.0, capital=5000.0, closes=prices)
    assert grid["ok"] is True
    assert len(grid["levels"]) >= 3
    assert grid["lower"] < grid["mid"] < grid["upper"]

    bare = propose_grid(symbol="BTC-USD", mid=None, closes=None)
    assert bare["ok"] is False
    assert bare.get("mid") is None
    assert "100" not in str(bare.get("error", ""))
    assert "нет" in bare["error"].lower()


def test_engine_actions_without_optional_packages():
    nautilus = get_engine("nautilus-trader")
    out = nautilus.action(kind="event_driven_backtest", prices=[100 + i * 0.3 for i in range(50)])
    assert out.get("ok") is True
    assert out["result"]["engine"] == "event_driven"

    hum = get_engine("hummingbot")
    grid = hum.action(
        kind="propose_grid",
        symbol="ETH-USD",
        mid=3000.0,
        capital=2000.0,
        prices=[3000 + i * 2.0 for i in range(40)],
    )
    assert grid.get("ok") is True
    assert grid.get("num_levels", 0) >= 2

    no_cap = hum.action(
        kind="propose_grid",
        symbol="ETH-USD",
        mid=3000.0,
        prices=[3000 + i * 2.0 for i in range(40)],
    )
    assert no_cap.get("ok") is False
    assert "10000" not in str(no_cap)
    assert "капитал" in str(no_cap.get("error", "")).lower()

    fin = get_engine("finrl")
    score = fin.action(kind="policy_score", prices=[100 + i * 0.1 for i in range(40)])
    assert score.get("ok") is True

    lumi = get_engine("lumibot")
    bt = lumi.action(kind="sample_backtest", prices=[100 * (1.002**i) for i in range(80)])
    assert bt.get("ok") is True
    assert "total_return" in bt["result"]


def test_finrl_train_then_infer(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FINRL_MODEL_DIR", str(tmp_path))
    from app.services.trading_engines.runtime.finrl_agent import train_and_save
    from app.services.trading_engines.runtime.finrl_policy import policy_score

    prices = [100.0 * (1.0015**i) for i in range(80)]
    trained = train_and_save(prices, symbol="TEST", episodes=8, seed=3)
    assert trained["ok"] is True
    scored = policy_score(prices, symbol="TEST")
    assert scored["trained"] is True
    assert scored["mode"] in {"trained_ppo", "trained_q_learning"}
    assert scored["direction"] in (-1, 0, 1)


def test_engine_intent_never_routes_to_venue():
    from app.services.trading_engines.runtime.intent import EngineIntent, gate_engine_intent

    approved = gate_engine_intent(
        EngineIntent(source="test", symbol="AAPL", side="long", confidence=0.6, suggested_weight=0.40)
    )
    assert approved["execution"] == "none"
    assert approved["paper_only"] is True
    assert approved["capped_weight"] <= 0.08
    assert approved["raw_suggested_weight"] == 0.40

    blocked = gate_engine_intent(
        EngineIntent(source="test", symbol="AAPL", side="long", confidence=0.6, suggested_weight=0.50)
    )
    # Cap brings weight inside limit; venue still untouched.
    assert blocked["execution"] == "none"


def test_trading_engines_router_registered():
    import ast
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "api" / "v1" / "endpoints" / "trading_engines.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    routes: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in {"get", "post"} and node.args:
                arg0 = node.args[0]
                if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
                    routes.append(arg0.value)
    assert "/health" in routes
    assert "/alpaca/data-status" in routes
    assert "/{name}/status" in routes
    assert "/{name}/action" in routes
