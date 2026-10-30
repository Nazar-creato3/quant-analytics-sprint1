"""CryptoDevTools — path-based tool runner for a safe pure utility (Lamports→SOL)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from app.services.crypto_stack.integrations.base import status_payload
from app.services.crypto_stack.integrations.paths import path_status, third_party_path

NAME = "cryptodevtools"
DIRNAME = "CryptoDevTools"
DOCS = "https://github.com/ChipaDevTeam/CryptoDevTools"


class CryptoDevToolsIntegration:
    name = NAME

    def status(self) -> dict[str, Any]:
        base = path_status(DIRNAME)
        root = third_party_path(DIRNAME)
        pkg = root / "CryptoDevTools"
        helper = pkg / "solana" / "helpers" / "LamportsToSol.py"
        has_helper = helper.is_file() if base["installed"] else False
        return status_payload(
            name=NAME,
            installed=base["installed"],
            runnable=has_helper,
            mode="path_tool",
            docs=DOCS,
            detail={
                **base,
                "package_root": str(pkg) if pkg.is_dir() else None,
                "lamports_helper": has_helper,
                "chains": self._list_chain_dirs(pkg) if pkg.is_dir() else [],
            },
            error=None if base["installed"] else "third_party/CryptoDevTools not cloned",
        )

    def capabilities(self) -> dict[str, Any]:
        return {
            "name": NAME,
            "actions": ["lamports_to_sol", "list_modules"],
            "notes": (
                "No pip package on repo root — adapters load helpers by path. "
                "RPC/trading clients need network keys; default action is pure math."
            ),
        }

    def action(self, **kwargs: Any) -> dict[str, Any]:
        st = self.status()
        if not st.get("installed"):
            return {"ok": False, "action": "probe", "error": st.get("error")}

        kind = (kwargs.get("kind") or "lamports_to_sol").lower()
        root = third_party_path(DIRNAME)
        pkg = root / "CryptoDevTools"

        if kind == "list_modules":
            return {
                "ok": True,
                "action": "list_modules",
                "chains": self._list_chain_dirs(pkg),
                "helpers": ["solana.helpers.LamportsToSol"],
            }

        try:
            lamports = int(kwargs.get("lamports", 1_000_000_000))
        except (TypeError, ValueError):
            return {"ok": False, "action": "lamports_to_sol", "error": "invalid_lamports"}

        try:
            sol = self._convert_lamports(pkg, lamports)
            return {
                "ok": True,
                "action": "lamports_to_sol",
                "lamports": lamports,
                "sol": sol,
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "action": "lamports_to_sol",
                "error": f"{type(exc).__name__}: {exc}",
            }

    @staticmethod
    def _list_chain_dirs(pkg: Path) -> list[str]:
        names: list[str] = []
        for child in sorted(pkg.iterdir()):
            if child.is_dir() and not child.name.startswith(("_", ".")) and child.name != "__pycache__":
                names.append(child.name)
        return names

    @staticmethod
    def _convert_lamports(pkg: Path, lamports: int) -> float:
        helper = pkg / "solana" / "helpers" / "LamportsToSol.py"
        if not helper.is_file():
            raise FileNotFoundError(str(helper))
        # Load module by path without permanently polluting sys.path with the monorepo.
        parent = str(pkg.parent)
        inserted = False
        if parent not in sys.path:
            sys.path.insert(0, parent)
            inserted = True
        try:
            spec = importlib.util.spec_from_file_location(
                "apex_cdt_lamports",
                helper,
            )
            if spec is None or spec.loader is None:
                raise ImportError("spec_load_failed")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            cls = getattr(mod, "LamportsToSol")
            return float(cls.convert(lamports))
        finally:
            if inserted:
                try:
                    sys.path.remove(parent)
                except ValueError:
                    pass
