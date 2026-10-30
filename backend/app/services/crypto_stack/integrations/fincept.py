"""FinceptTerminal — native Qt desktop terminal (launch + local data bridge).

Fincept is a C++/Qt6 desktop app. It does **not** expose a documented local HTTP/WebSocket
API for embedding. QuantAnalytics binds via:

- process launch / status (only when API runs on the same Windows host as Fincept.exe)
- read-only SQLite + AppData panels (watchlists, notebooks, settings keys)
- push QuantAnalytics tickers into Fincept `historify_watchlist` + bridge JSON file

Production (Linux VPS) correctly reports missing binary. Browser operators must run
`tools/fincept_companion` on 127.0.0.1:17890 — the Terminal page prefers that agent.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.crypto_stack.integrations.base import status_payload
from app.services.crypto_stack.integrations.paths import path_status, third_party_path

NAME = "fincept-terminal"
DIRNAME = "FinceptTerminal"
DOCS = "https://github.com/Fincept-Corporation/FinceptTerminal"
RELEASES = "https://github.com/Fincept-Corporation/FinceptTerminal/releases"
BRIDGE_FILENAME = "apex_watchlist_bridge.json"

# Never surface credential / API key rows from Fincept local DBs.
_SENSITIVE_KEY_FRAGMENTS = (
    "api_key",
    "apikey",
    "secret",
    "password",
    "token",
    "credential",
    "private",
)


class FinceptTerminalIntegration:
    name = NAME

    def status(self) -> dict[str, Any]:
        base = path_status(DIRNAME)
        root = third_party_path(DIRNAME)
        readme = (root / "README.md").is_file() if base["installed"] else False
        dockerfile = (root / "Dockerfile").is_file() if base["installed"] else False
        exe, reachable = self._resolve_binary(root if base["installed"] else None)
        appdata = self._appdata_root()
        appdata_ok = appdata.is_dir()
        running = self._process_running()
        local = self._local_snapshot(limit=12) if appdata_ok else {"ok": False, "error": "no_appdata"}
        # Installer-only hosts count as installed when a binary path is known.
        installed = bool(base["installed"] or exe or appdata_ok)
        runnable = bool(exe) and (reachable or bool(os.environ.get("FINCEPT_TERMINAL_EXE", "").strip()))
        err = None
        if not installed:
            err = "third_party/FinceptTerminal not cloned and FINCEPT_TERMINAL_EXE unset"
        elif not runnable and sys.platform != "win32":
            err = (
                "binary not reachable from this host (Linux VPS). "
                "Run tools/fincept_companion on the Windows PC (127.0.0.1:17890)"
            )
        return status_payload(
            name=NAME,
            installed=installed,
            runnable=runnable,
            mode="desktop_sidecar",
            docs=DOCS,
            detail={
                **base,
                "readme": readme,
                "dockerfile": dockerfile,
                "binary": exe,
                "binary_reachable": reachable,
                "releases": RELEASES,
                "start_script": "scripts/start-fincept-info.ps1",
                "appdata": str(appdata) if appdata_ok else None,
                "appdata_present": appdata_ok,
                "process_running": running,
                "embed_api": False,
                "embed_note": (
                    "Qt desktop only — no iframe embed. "
                    "On Linux VPS use tools/fincept_companion (127.0.0.1:17890) from the browser."
                ),
                "companion": {
                    "preferred": True,
                    "base_url": "http://127.0.0.1:17890",
                    "start_script": "tools/fincept_companion/start-companion.ps1",
                    "readme": "tools/fincept_companion/README.md",
                },
                "local": local,
                "hub_path": "/terminal",
            },
            error=err,
        )

    def capabilities(self) -> dict[str, Any]:
        return {
            "name": NAME,
            "actions": [
                "probe",
                "launch_info",
                "launch",
                "local_snapshot",
                "push_watchlist",
            ],
            "notes": (
                "C++/Qt6 desktop app — not imported into uvicorn and not embeddable in iframe. "
                "Launch opens FinceptTerminal.exe; push_watchlist writes bridge JSON + historify_watchlist."
            ),
            "env": ["FINCEPT_TERMINAL_EXE"],
            "ui": {"hub": "/terminal", "integrations": "/ops/crypto-integrations"},
            "companion": "tools/fincept_companion",
        }

    def action(self, **kwargs: Any) -> dict[str, Any]:
        st = self.status()
        which = (kwargs.get("kind") or "probe").lower()

        if which == "launch_info":
            return {
                "ok": True,
                "action": "launch_info",
                "releases": RELEASES,
                "docs": DOCS,
                "binary": st.get("detail", {}).get("binary"),
                "hint": (
                    "Download Windows installer from releases, or set FINCEPT_TERMINAL_EXE "
                    "to FinceptTerminal.exe path. Run scripts/start-fincept-info.ps1."
                ),
                "start_script": "scripts/start-fincept-info.ps1",
                "embed_api": False,
            }

        if which == "launch":
            return self._launch()

        if which == "local_snapshot":
            snap = self._local_snapshot(limit=int(kwargs.get("limit") or 40))
            snap["action"] = "local_snapshot"
            return snap

        if which == "push_watchlist":
            symbols = kwargs.get("symbols") or kwargs.get("tickers") or []
            if isinstance(symbols, str):
                symbols = [s.strip() for s in symbols.split(",") if s.strip()]
            if not isinstance(symbols, list):
                return {"ok": False, "action": "push_watchlist", "error": "symbols_must_be_list"}
            return self._push_watchlist([str(s) for s in symbols])

        return {
            "ok": bool(st.get("installed")),
            "action": "probe",
            "installed": st.get("installed"),
            "runnable": st.get("runnable"),
            "binary": st.get("detail", {}).get("binary"),
            "process_running": st.get("detail", {}).get("process_running"),
            "appdata_present": st.get("detail", {}).get("appdata_present"),
            "embed_api": False,
            "error": st.get("error"),
        }

    # ── launch / process ─────────────────────────────────────────────────────

    def _launch(self) -> dict[str, Any]:
        root = third_party_path(DIRNAME)
        exe, reachable = self._resolve_binary(root if root.is_dir() else None)
        if not exe:
            return {
                "ok": False,
                "action": "launch",
                "error": "binary_not_found",
                "releases": RELEASES,
                "hint": "Install FinceptTerminal or set FINCEPT_TERMINAL_EXE",
            }
        if not reachable and not Path(exe).is_file():
            return {
                "ok": False,
                "action": "launch",
                "error": "binary_not_reachable_from_this_process",
                "binary": exe,
                "hint": "Run scripts/start-fincept-info.ps1 on the Windows host",
            }
        try:
            if sys.platform == "win32":
                subprocess.Popen(  # noqa: S603 — fixed binary path from resolver
                    [exe],
                    cwd=str(Path(exe).parent),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
                    | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
                )
            else:
                subprocess.Popen(  # noqa: S603
                    [exe],
                    cwd=str(Path(exe).parent),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
            return {
                "ok": True,
                "action": "launch",
                "binary": exe,
                "note": "Fincept opens in its own Qt window — not embedded in QuantAnalytics.",
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "action": "launch",
                "error": f"{type(exc).__name__}: {exc}",
                "binary": exe,
            }

    @staticmethod
    def _process_running() -> bool:
        if sys.platform != "win32":
            return False
        try:
            proc = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq FinceptTerminal.exe", "/NH"],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
            out = (proc.stdout or "").lower()
            return "finceptterminal.exe" in out
        except Exception:  # noqa: BLE001
            return False

    # ── AppData / SQLite bridge ──────────────────────────────────────────────

    @staticmethod
    def _appdata_root() -> Path:
        override = os.environ.get("FINCEPT_APPDATA", "").strip()
        if override:
            return Path(override)
        local = os.environ.get("LOCALAPPDATA", "").strip()
        if local:
            return Path(local) / "com.fincept.terminal"
        return Path.home() / "AppData" / "Local" / "com.fincept.terminal"

    def _bridge_path(self) -> Path:
        return self._appdata_root() / "files" / BRIDGE_FILENAME

    def _db_path(self) -> Path:
        return self._appdata_root() / "data" / "fincept.db"

    def _local_snapshot(self, *, limit: int = 40) -> dict[str, Any]:
        root = self._appdata_root()
        if not root.is_dir():
            return {"ok": False, "error": "appdata_missing", "path": str(root)}

        files_dir = root / "files"
        notebooks: list[dict[str, Any]] = []
        meta_path = files_dir / "metadata.json"
        if meta_path.is_file():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                entries = meta.get("files") if isinstance(meta, dict) else None
                if isinstance(entries, list):
                    for item in entries[:limit]:
                        if isinstance(item, dict):
                            notebooks.append(
                                {
                                    "name": item.get("name") or item.get("title") or item.get("id"),
                                    "id": item.get("id"),
                                    "path": item.get("path") or item.get("file"),
                                }
                            )
            except Exception as exc:  # noqa: BLE001
                notebooks = [{"error": f"metadata: {type(exc).__name__}"}]

        if not notebooks and files_dir.is_dir():
            for p in sorted(files_dir.glob("*.ipynb"))[:limit]:
                notebooks.append({"name": p.name, "path": str(p)})

        bridge = self._bridge_path()
        bridge_info: dict[str, Any] | None = None
        if bridge.is_file():
            try:
                raw = json.loads(bridge.read_text(encoding="utf-8"))
                bridge_info = {
                    "path": str(bridge),
                    "updated_at": raw.get("updated_at"),
                    "symbol_count": len(raw.get("symbols") or []),
                    "symbols": (raw.get("symbols") or [])[:limit],
                }
            except Exception as exc:  # noqa: BLE001
                bridge_info = {"path": str(bridge), "error": type(exc).__name__}

        db = self._db_path()
        db_payload: dict[str, Any] = {"path": str(db), "present": db.is_file()}
        if db.is_file():
            try:
                db_payload.update(self._read_db_safe(db, limit=limit))
                db_payload["ok"] = True
            except Exception as exc:  # noqa: BLE001
                db_payload["ok"] = False
                db_payload["error"] = f"{type(exc).__name__}: {exc}"

        layouts = root / "layouts"
        return {
            "ok": True,
            "appdata": str(root),
            "notebooks": notebooks,
            "bridge": bridge_info,
            "db": db_payload,
            "layouts_present": layouts.is_dir(),
            "process_running": self._process_running(),
            "embed_api": False,
        }

    @classmethod
    def _read_db_safe(cls, db: Path, *, limit: int) -> dict[str, Any]:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            tables = {
                r[0]
                for r in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            out: dict[str, Any] = {"tables_sample": sorted(tables)[:40]}

            if "historify_watchlist" in tables:
                rows = con.execute(
                    "SELECT symbol, exchange, interval, added_at "
                    "FROM historify_watchlist ORDER BY added_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
                out["historify_watchlist"] = [
                    {"symbol": r[0], "exchange": r[1], "interval": r[2], "added_at": r[3]}
                    for r in rows
                ]

            if "watchlists" in tables:
                wls = con.execute(
                    "SELECT id, name, is_default FROM watchlists ORDER BY sort_order, id LIMIT ?",
                    (limit,),
                ).fetchall()
                out["watchlists"] = [
                    {"id": r[0], "name": r[1], "is_default": bool(r[2])} for r in wls
                ]

            if "watchlist_stocks" in tables:
                stocks = con.execute(
                    "SELECT symbol, name, exchange FROM watchlist_stocks "
                    "ORDER BY sort_order, id LIMIT ?",
                    (limit,),
                ).fetchall()
                out["watchlist_stocks"] = [
                    {"symbol": r[0], "name": r[1], "exchange": r[2]} for r in stocks
                ]

            if "settings" in tables:
                settings_rows = con.execute(
                    "SELECT key, category FROM settings LIMIT ?",
                    (limit,),
                ).fetchall()
                out["settings_keys"] = [
                    {"key": r[0], "category": r[1]}
                    for r in settings_rows
                    if not cls._is_sensitive_key(str(r[0]))
                ]

            if "instruments" in tables:
                n = con.execute("SELECT COUNT(*) FROM instruments").fetchone()[0]
                out["instruments_count"] = n

            return out
        finally:
            con.close()

    @classmethod
    def _is_sensitive_key(cls, key: str) -> bool:
        low = key.lower()
        return any(frag in low for frag in _SENSITIVE_KEY_FRAGMENTS)

    def _push_watchlist(self, symbols: list[str]) -> dict[str, Any]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for raw in symbols:
            sym = str(raw).strip().upper()
            if not sym or sym in seen:
                continue
            seen.add(sym)
            cleaned.append(sym)
        if not cleaned:
            return {"ok": False, "action": "push_watchlist", "error": "empty_symbols"}

        root = self._appdata_root()
        files_dir = root / "files"
        try:
            files_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "action": "push_watchlist",
                "error": f"appdata_mkdir: {type(exc).__name__}: {exc}",
            }

        payload = {
            "source": "quantanalytics",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "symbols": cleaned,
            "note": (
                "Bridge file written by QuantAnalytics. Fincept may need a restart/refresh "
                "to pick up historify_watchlist rows; chart UI stays in the Fincept window."
            ),
        }
        bridge = self._bridge_path()
        bridge.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        db_result: dict[str, Any] = {"updated": False}
        db = self._db_path()
        if db.is_file():
            try:
                db_result = self._upsert_historify(db, cleaned)
            except Exception as exc:  # noqa: BLE001
                db_result = {"updated": False, "error": f"{type(exc).__name__}: {exc}"}
        else:
            db_result = {"updated": False, "error": "fincept.db_missing"}

        return {
            "ok": True,
            "action": "push_watchlist",
            "bridge_path": str(bridge),
            "symbols": cleaned,
            "count": len(cleaned),
            "db": db_result,
            "hint": (
                "Open Fincept desktop to use charts/agents. "
                "QuantAnalytics cannot embed the Qt UI — use Companion on Windows."
            ),
        }

    @staticmethod
    def _upsert_historify(db: Path, symbols: list[str]) -> dict[str, Any]:
        con = sqlite3.connect(str(db))
        try:
            tables = {
                r[0]
                for r in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if "historify_watchlist" not in tables:
                return {"updated": False, "error": "historify_watchlist_table_missing"}
            now = datetime.now(timezone.utc).isoformat()
            inserted = 0
            for sym in symbols:
                # symbol is PK in observed schema
                con.execute(
                    "INSERT INTO historify_watchlist(symbol, exchange, interval, added_at) "
                    "VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(symbol) DO UPDATE SET added_at=excluded.added_at",
                    (sym, "CRYPTO", "1d", now),
                )
                inserted += 1
            con.commit()
            return {"updated": True, "rows": inserted, "table": "historify_watchlist"}
        finally:
            con.close()

    # ── binary discovery ─────────────────────────────────────────────────────

    @classmethod
    def _resolve_binary(cls, root: Path | None) -> tuple[str | None, bool]:
        """Return (path, reachable_from_this_process)."""
        env_bin = os.environ.get("FINCEPT_TERMINAL_EXE", "").strip()
        if env_bin:
            if Path(env_bin).is_file():
                return env_bin, True
            # Env set (e.g. Docker on Windows host) — launch is host-side via start script.
            return env_bin, False

        if root is not None:
            found = cls._find_in_clone(root)
            if found:
                return found, True

        for c in cls._windows_install_candidates():
            if c.is_file():
                return str(c), True

        which = shutil.which("FinceptTerminal")
        if which:
            return which, True
        return None, False

    @staticmethod
    def _find_in_clone(root: Path) -> str | None:
        candidates = [
            root / "FinceptTerminal.exe",
            root / "build" / "FinceptTerminal.exe",
            root / "fincept-qt" / "build" / "FinceptTerminal.exe",
        ]
        for c in candidates:
            if c.is_file():
                return str(c)
        return None

    @staticmethod
    def _windows_install_candidates() -> list[Path]:
        out: list[Path] = []
        for key in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            base = os.environ.get(key, "").strip()
            if not base:
                continue
            if key == "LOCALAPPDATA":
                out.append(Path(base) / "Programs" / "FinceptTerminal" / "FinceptTerminal.exe")
            else:
                out.append(Path(base) / "FinceptTerminal" / "FinceptTerminal.exe")
        out.append(Path(r"C:\Program Files\FinceptTerminal\FinceptTerminal.exe"))
        return out
