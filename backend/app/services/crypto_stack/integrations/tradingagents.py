"""tradingagents — multi-agent LLM framework (subprocess / path probe, not in-worker monorepo)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from app.services.crypto_stack.integrations.base import status_payload
from app.services.crypto_stack.integrations.paths import path_status, third_party_path

NAME = "tradingagents"
DIRNAME = "tradingagents"
DOCS = "https://github.com/TauricResearch/TradingAgents"


class TradingAgentsIntegration:
    name = NAME

    def status(self) -> dict[str, Any]:
        base = path_status(DIRNAME)
        root = third_party_path(DIRNAME)
        pkg = root / "tradingagents"
        main_py = root / "main.py"
        has_pkg = pkg.is_dir() and (pkg / "__init__.py").exists() if base["installed"] else False
        return status_payload(
            name=NAME,
            installed=base["installed"],
            runnable=has_pkg,
            mode="subprocess_cli",
            docs=DOCS,
            detail={
                **base,
                "package_dir": str(pkg) if has_pkg else None,
                "main_py": main_py.is_file() if base["installed"] else False,
                "start_script": "scripts/start-tradingagents-probe.ps1",
                "requires_llm_keys": True,
            },
            error=None if base["installed"] else "third_party/tradingagents not cloned",
        )

    def capabilities(self) -> dict[str, Any]:
        return {
            "name": NAME,
            "actions": ["probe_import", "sample_ticker"],
            "notes": (
                "Heavy LangChain stack — probed via short-lived subprocess. "
                "Full agent run needs LLM API keys (OPENAI_API_KEY / TRADINGAGENTS_*)."
            ),
            "env": ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "TRADINGAGENTS_LLM_PROVIDER"],
        }

    def action(self, **kwargs: Any) -> dict[str, Any]:
        st = self.status()
        if not st.get("installed"):
            return {"ok": False, "action": "probe", "error": st.get("error")}

        kind = (kwargs.get("kind") or "probe_import").lower()
        root = third_party_path(DIRNAME)
        timeout = float(kwargs.get("timeout") or os.environ.get("TRADINGAGENTS_PROBE_TIMEOUT", "25"))

        if kind == "sample_ticker":
            ticker = str(kwargs.get("ticker") or "NVDA")
            # Full graph run is expensive; only attempt if explicitly enabled.
            if os.environ.get("TRADINGAGENTS_ALLOW_FULL_RUN", "").lower() not in {"1", "true", "yes"}:
                return {
                    "ok": False,
                    "action": "sample_ticker",
                    "error": (
                        "full_run_disabled: set TRADINGAGENTS_ALLOW_FULL_RUN=1 and LLM keys, "
                        "or use scripts/start-tradingagents-probe.ps1. Default action is probe_import."
                    ),
                    "ticker": ticker,
                    "hint": "Run: python main.py inside third_party/tradingagents with .env",
                }
            return self._run_sample(root, ticker, timeout)

        return self._probe_import(root, timeout)

    def _probe_import(self, root: Path, timeout: float) -> dict[str, Any]:
        code = (
            "import sys; sys.path.insert(0, r%r); "
            "from tradingagents.default_config import DEFAULT_CONFIG; "
            "print('ok', len(DEFAULT_CONFIG))"
        ) % str(root)
        try:
            proc = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(root),
                env={**os.environ, "PYTHONPATH": str(root)},
            )
            if proc.returncode != 0:
                err = (proc.stderr or proc.stdout or "").strip()[:800]
                return {
                    "ok": False,
                    "action": "probe_import",
                    "error": err or f"exit_{proc.returncode}",
                    "hint": "pip install -r third_party/tradingagents/requirements.txt in a dedicated venv",
                }
            return {
                "ok": True,
                "action": "probe_import",
                "stdout": (proc.stdout or "").strip()[:400],
            }
        except subprocess.TimeoutExpired:
            return {"ok": False, "action": "probe_import", "error": f"timeout_after_{timeout}s"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "action": "probe_import", "error": f"{type(exc).__name__}: {exc}"}

    def _run_sample(self, root: Path, ticker: str, timeout: float) -> dict[str, Any]:
        code = (
            "import sys; sys.path.insert(0, r%r); "
            "from tradingagents.default_config import DEFAULT_CONFIG; "
            "from tradingagents.graph.trading_graph import TradingAgentsGraph; "
            "cfg=DEFAULT_CONFIG.copy(); "
            "ta=TradingAgentsGraph(debug=False, config=cfg); "
            "_, decision = ta.propagate(%r, '2024-05-10'); "
            "print(decision)"
        ) % (str(root), ticker)
        try:
            proc = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(root),
                env={**os.environ, "PYTHONPATH": str(root)},
            )
            if proc.returncode != 0:
                err = (proc.stderr or proc.stdout or "").strip()[:1000]
                return {
                    "ok": False,
                    "action": "sample_ticker",
                    "ticker": ticker,
                    "error": err or f"exit_{proc.returncode}",
                }
            return {
                "ok": True,
                "action": "sample_ticker",
                "ticker": ticker,
                "stdout": (proc.stdout or "").strip()[:2000],
            }
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "action": "sample_ticker",
                "ticker": ticker,
                "error": f"timeout_after_{timeout}s",
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "action": "sample_ticker",
                "ticker": ticker,
                "error": f"{type(exc).__name__}: {exc}",
            }
