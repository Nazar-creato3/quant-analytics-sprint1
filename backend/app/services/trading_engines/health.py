"""Aggregate health for trading engines, GitHub repos, and MCP servers."""
from __future__ import annotations

import os
from typing import Any

from app.services.github.client import GitHubClient
from app.services.trading_engines.registry import ENGINE_NAMES, list_engines

# GitHub owner/repo for each engine (Backtrader excluded)
_GITHUB_REPOS: dict[str, tuple[str, str]] = {
    "ccxt": ("ccxt", "ccxt"),
    "vectorbt": ("polakowo", "vectorbt"),
    "nautilus-trader": ("nautechsystems", "nautilus_trader"),
    "freqtrade": ("freqtrade", "freqtrade"),
    "hummingbot": ("hummingbot", "hummingbot"),
    "tradingagents": ("TauricResearch", "TradingAgents"),
    "finrl": ("AI4Finance-Foundation", "FinRL"),
    "lumibot": ("Lumiwealth", "lumibot"),
}


def mcp_health() -> dict[str, Any]:
    """Probe MCP-related packages (process health is Cursor-side)."""
    from app.services.crypto_stack.health import _probe

    servers = [
        ("binance_context_server", "binance_context_server", "BINANCE_API_KEY"),
        ("crypto_powerdata_mcp", "src", None),
        ("dune", "dune_client", "DUNE_API_KEY"),
        ("supabase", "supabase", "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY"),
    ]
    items: list[dict[str, Any]] = []
    for name, import_path, env_key in servers:
        probe = _probe(name, import_path)
        env_present = bool(os.getenv(env_key)) if env_key else True
        ok = probe.get("available") and probe.get("importable", True) and env_present
        if name == "dune" and not env_present:
            probe = {**probe, "skipped": "DUNE_API_KEY not set"}
            ok = False
        items.append(
            {
                "name": name,
                "ok": ok,
                "env_configured": env_present,
                "probe": probe,
            }
        )
    ok_count = sum(1 for i in items if i["ok"])
    return {
        "ok": ok_count >= 1,
        "available_count": ok_count,
        "total": len(items),
        "servers": items,
        "note": "MCP host processes run in Cursor (.venv-mcp); this probes Python packages + env.",
    }


def github_repos_health(*, check_remote: bool = False) -> dict[str, Any]:
    """Local engine status + optional GitHub API repo metadata."""
    client = GitHubClient()
    repos: list[dict[str, Any]] = []
    for engine_name in ENGINE_NAMES:
        owner, repo = _GITHUB_REPOS[engine_name]
        entry: dict[str, Any] = {"engine": engine_name, "owner": owner, "repo": repo}
        if check_remote:
            entry["remote"] = client.repo_health(owner, repo)
        else:
            entry["remote_skipped"] = True
            entry["token_configured"] = client.token_configured
        repos.append(entry)
    return {
        "token_configured": client.token_configured,
        "repos": repos,
    }


def engines_health(*, github_check: bool = False) -> dict[str, Any]:
    """Full trading-engines health payload for ops UI."""
    engines = list_engines()
    runnable = sum(1 for e in engines if e.get("runnable"))
    ok = sum(1 for e in engines if e.get("ok"))
    mcp = mcp_health()
    github = github_repos_health(check_remote=github_check)
    from app.services.trading_engines.runtime.alpaca_data import alpaca_data_status

    return {
        "ok": ok >= 1,
        "engine_count": len(engines),
        "engines_ok": ok,
        "engines_runnable": runnable,
        "expected": list(ENGINE_NAMES),
        "engines": engines,
        "excluded": {
            "backtrader": {
                "repo": "https://github.com/mementum/backtrader",
                "reason": "unmaintained; Apex uses terminal quant + VectorBT overlay",
            },
            "alpaca-backtrader-api": {
                "repo": "https://github.com/alpacahq/alpaca-backtrader-api",
                "reason": "depends on unmaintained Backtrader; use native AlpacaExecutor (paper quotes / user keys)",
            },
        },
        "mcp": mcp,
        "github": github,
        "alpaca_data": alpaca_data_status(),
    }
