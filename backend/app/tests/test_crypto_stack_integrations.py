"""Unit tests for crypto_stack third_party integrations (mock-friendly, no Docker)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.crypto_stack.integrations import (
    INTEGRATION_NAMES,
    get_integration,
    list_integrations,
)
from app.services.crypto_stack.integrations.base import status_payload
from app.services.crypto_stack.integrations.ccxt_pip import CcxtPipIntegration
from app.services.crypto_stack.integrations.cryptodevtools import CryptoDevToolsIntegration
from app.services.crypto_stack.integrations.paths import path_status, repo_root


EXPECTED = {
    "tradingagents",
    "cryptodevtools",
    "crypto-analytics-platform",
    "crypto-pulse-ai",
    "opentao-api",
    "celebrum-ai-go",
    "ccxt",
}


def test_registry_has_seven_names():
    assert set(INTEGRATION_NAMES) == EXPECTED
    assert len(INTEGRATION_NAMES) == 7
    for name in EXPECTED:
        assert get_integration(name) is not None
    assert get_integration("nope") is None


def test_status_payload_shape():
    p = status_payload(
        name="demo",
        installed=True,
        runnable=False,
        mode="test",
        error=None,
        docs="https://example.com",
        detail={"path": "/tmp"},
    )
    assert p["name"] == "demo"
    assert p["installed"] is True
    assert p["runnable"] is False
    assert p["ok"] is True
    assert p["mode"] == "test"
    assert p["detail"]["path"] == "/tmp"


def test_path_status_respects_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APEX_THIRD_PARTY_ROOT", str(tmp_path))
    (tmp_path / "FinceptTerminal").mkdir()
    st = path_status("FinceptTerminal")
    assert st["installed"] is True
    assert st["path_exists"] is True
    missing = path_status("no_such_clone")
    assert missing["installed"] is False


def test_list_integrations_shape(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("APEX_THIRD_PARTY_ROOT", str(tmp_path))
    # empty third_party → installed flags mostly false except pip ccxt
    items = list_integrations()
    assert len(items) == 7
    names = {i["name"] for i in items}
    assert names == EXPECTED
    for item in items:
        assert "installed" in item
        assert "runnable" in item
        assert "ok" in item
        assert "mode" in item
        assert "name" in item


def test_ccxt_action_exchange_count():
    adapter = CcxtPipIntegration()
    st = adapter.status()
    assert st["name"] == "ccxt"
    assert st["mode"] == "pip_production"
    assert "reference_clone" in st["detail"]
    # Never mounts clone — production note present
    assert "pip" in st["detail"]["reference_note"].lower() or "PYTHONPATH" in st["detail"]["reference_note"]

    result = adapter.action(kind="exchange_count")
    if result.get("ok"):
        assert isinstance(result["count"], int)
        assert result["count"] > 0
        assert result["source"] == "pip"
    else:
        assert "pip_ccxt_missing" in str(result.get("error", ""))


def test_cryptodevtools_lamports_with_fake_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APEX_THIRD_PARTY_ROOT", str(tmp_path))
    helper = (
        tmp_path
        / "CryptoDevTools"
        / "CryptoDevTools"
        / "solana"
        / "helpers"
        / "LamportsToSol.py"
    )
    helper.parent.mkdir(parents=True)
    helper.write_text(
        "class LamportsToSol:\n"
        "    @staticmethod\n"
        "    def convert(lamports: int) -> float:\n"
        "        return lamports / 1_000_000_000\n",
        encoding="utf-8",
    )
    adapter = CryptoDevToolsIntegration()
    st = adapter.status()
    assert st["installed"] is True
    assert st["runnable"] is True
    out = adapter.action(kind="lamports_to_sol", lamports=2_000_000_000)
    assert out["ok"] is True
    assert out["sol"] == 2.0


def test_crypto_analytics_proxy_mocked(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("APEX_THIRD_PARTY_ROOT", str(tmp_path))
    (tmp_path / "crypto-analytics-platform").mkdir()
    (tmp_path / "crypto-analytics-platform" / "docker-compose.yml").write_text("services: {}\n")
    monkeypatch.setenv("CAP_BACKEND_URL", "http://127.0.0.1:18000")

    from app.services.crypto_stack.integrations.crypto_analytics import CryptoAnalyticsIntegration

    adapter = CryptoAnalyticsIntegration()
    with patch(
        "app.services.crypto_stack.integrations.crypto_analytics.probe_url",
        return_value={"reachable": True, "ok": True, "status_code": 200, "url": "x"},
    ):
        st = adapter.status()
        assert st["installed"] is True
        assert st["runnable"] is True

    with patch(
        "app.services.crypto_stack.integrations.crypto_analytics.proxy_get",
        return_value={"ok": True, "status_code": 200, "body": {"status": "ok"}},
    ) as prox:
        result = adapter.action(kind="proxy_get", path="health")
        assert result["ok"] is True
        prox.assert_called_once()


def test_fincept_missing_clone(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("APEX_THIRD_PARTY_ROOT", str(tmp_path))
    monkeypatch.delenv("FINCEPT_TERMINAL_EXE", raising=False)
    monkeypatch.setenv("FINCEPT_APPDATA", str(tmp_path / "no_fincept_appdata"))
    from app.services.crypto_stack.integrations.fincept import FinceptTerminalIntegration

    monkeypatch.setattr(
        FinceptTerminalIntegration,
        "_windows_install_candidates",
        staticmethod(lambda: []),
    )
    monkeypatch.setattr(
        "app.services.crypto_stack.integrations.fincept.shutil.which",
        lambda _name: None,
    )
    monkeypatch.setattr(
        FinceptTerminalIntegration,
        "_process_running",
        staticmethod(lambda: False),
    )

    adapter = FinceptTerminalIntegration()
    st = adapter.status()
    assert st["installed"] is False
    assert st["ok"] is False
    assert st["detail"]["embed_api"] is False
    act = adapter.action(kind="launch_info")
    assert act["ok"] is True
    assert "releases" in act


def test_fincept_push_watchlist_bridge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APEX_THIRD_PARTY_ROOT", str(tmp_path))
    monkeypatch.delenv("FINCEPT_TERMINAL_EXE", raising=False)
    appdata = tmp_path / "com.fincept.terminal"
    (appdata / "data").mkdir(parents=True)
    (appdata / "files").mkdir(parents=True)
    monkeypatch.setenv("FINCEPT_APPDATA", str(appdata))

    import sqlite3

    db = appdata / "data" / "fincept.db"
    con = sqlite3.connect(str(db))
    con.execute(
        "CREATE TABLE historify_watchlist("
        "symbol TEXT PRIMARY KEY, exchange TEXT, interval TEXT, added_at TEXT)"
    )
    con.commit()
    con.close()

    from app.services.crypto_stack.integrations.fincept import FinceptTerminalIntegration

    monkeypatch.setattr(
        FinceptTerminalIntegration,
        "_windows_install_candidates",
        staticmethod(lambda: []),
    )
    monkeypatch.setattr(
        "app.services.crypto_stack.integrations.fincept.shutil.which",
        lambda _name: None,
    )

    adapter = FinceptTerminalIntegration()
    st = adapter.status()
    assert st["installed"] is True
    assert st["detail"]["appdata_present"] is True

    out = adapter.action(kind="push_watchlist", symbols=["btc", "ETH", "btc"])
    assert out["ok"] is True
    assert out["count"] == 2
    bridge = appdata / "files" / "apex_watchlist_bridge.json"
    assert bridge.is_file()
    snap = adapter.action(kind="local_snapshot")
    assert snap["ok"] is True
    assert snap["db"]["historify_watchlist"]


def test_integrations_router_paths_registered():
    import ast
    from pathlib import Path as P

    path = (
        P(__file__).resolve().parents[1]
        / "api"
        / "v1"
        / "endpoints"
        / "crypto_stack_integrations.py"
    )
    tree = ast.parse(path.read_text(encoding="utf-8"))
    routes: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in {"get", "post", "put", "delete"} and node.args:
                arg0 = node.args[0]
                if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
                    routes.append(arg0.value)
    assert "" in routes or "/" in routes
    assert "/{name}/status" in routes
    assert "/{name}/capabilities" in routes
    assert "/{name}/action" in routes
    assert "/{name}/proxy" in routes


def test_repo_root_resolves():
    root = repo_root()
    assert root.is_dir()
    assert (root / "backend").is_dir() or root.name == "backend"
