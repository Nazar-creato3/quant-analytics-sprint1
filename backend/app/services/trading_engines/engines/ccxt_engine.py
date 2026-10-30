"""CCXT — unified exchange data provider (Module 1: Data layer)."""
from __future__ import annotations

from typing import Any

from app.services.trading_engines.base import engine_status_payload
from app.services.trading_engines.probes import clone_status, probe_import

NAME = "ccxt"
OWNER = "ccxt"
REPO = "ccxt"
DOCS = "https://docs.ccxt.com/"


class CcxtEngine:
    name = NAME

    def status(self) -> dict[str, Any]:
        pip = probe_import("ccxt", "ccxt")
        clone = clone_status("ccxt")
        installed = pip.get("available", False)
        runnable = installed and pip.get("importable", False)
        exchange_count = None
        if runnable:
            try:
                import ccxt  # type: ignore

                exchange_count = len(list(getattr(ccxt, "exchanges", []) or []))
            except Exception:  # noqa: BLE001
                pass
        return engine_status_payload(
            name=NAME,
            module="data_layer",
            integration_mode="pip_dependency",
            license_id="MIT",
            installed=installed,
            runnable=runnable,
            github_owner=OWNER,
            github_repo=REPO,
            docs=DOCS,
            detail={
                "pip_version": pip.get("version"),
                "exchange_count": exchange_count,
                "reference_clone": clone,
                "provider_class": "CCXTProvider",
                "wired_to": [
                    "CCXTProvider (binance/bybit/okx)",
                    "universe_search source=ccxt",
                    "get_crypto_bars CCXT fallback",
                ],
            },
            error=pip.get("error"),
        )

    def capabilities(self) -> dict[str, Any]:
        return {
            "name": NAME,
            "module": "data_layer",
            "actions": ["exchange_count", "fetch_ticker_public", "fetch_ohlcv_public"],
            "exchanges": ["binance", "bybit", "okx", "kraken"],
        }

    def action(self, **kwargs: Any) -> dict[str, Any]:
        kind = (kwargs.get("kind") or "exchange_count").lower()
        try:
            import ccxt  # type: ignore
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"ccxt_missing: {exc}"}

        if kind in {"fetch_ticker_public", "fetch_ohlcv_public"}:
            exchange_id = (kwargs.get("exchange") or "binance").lower()
            symbol = kwargs.get("symbol") or "BTC/USDT"
            try:
                cls = getattr(ccxt, exchange_id)
                ex = cls({"enableRateLimit": True})
                if kind == "fetch_ohlcv_public":
                    tf = str(kwargs.get("timeframe") or "1d")
                    limit = int(kwargs.get("limit") or 50)
                    rows = ex.fetch_ohlcv(symbol, tf, limit=min(limit, 200))
                    closes = [float(r[4]) for r in rows or [] if r and len(r) > 4]
                    return {
                        "ok": True,
                        "exchange": exchange_id,
                        "symbol": symbol,
                        "timeframe": tf,
                        "bars": len(rows or []),
                        "last_close": closes[-1] if closes else None,
                        "source": "ccxt",
                    }
                raw = ex.fetch_ticker(symbol)
                return {
                    "ok": True,
                    "exchange": exchange_id,
                    "symbol": symbol,
                    "last": raw.get("last"),
                    "source": "ccxt",
                }
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        exchanges = list(getattr(ccxt, "exchanges", []) or [])
        return {
            "ok": True,
            "action": "exchange_count",
            "count": len(exchanges),
            "version": getattr(ccxt, "__version__", "unknown"),
        }
