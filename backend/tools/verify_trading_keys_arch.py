#!/usr/bin/env python3
"""Final architecture verification (run inside apex-backend container or on VPS)."""
import asyncio
import inspect
import json
import subprocess
import sys


def run(cmd: str) -> str:
    return subprocess.check_output(cmd, shell=True, text=True).strip()


async def main() -> int:
    results = {}

    # Modules
    from app.services.trading_keys import platform_keys
    from app.services.trading_keys.user_executor import resolve_execution_venue

    results["modules"] = {
        "platform_alpaca": bool(platform_keys.alpaca_data_headers()),
        "venue_aapl": resolve_execution_venue("AAPL"),
        "venue_btc": resolve_execution_venue("BTCUSDT"),
    }

    # Invalid key
    from app.services.trading_keys.validators import validate_binance_key

    bad = await validate_binance_key(api_key="x", api_secret="y")
    results["invalid_key_rejected"] = not bad.ok

    # Routes in source
    from app.api.v1.endpoints import trading_accounts

    results["routes"] = [getattr(r, "path", str(r)) for r in trading_accounts.router.routes]
    results["has_fallback_route"] = any(
        "fallback-status" in getattr(r, "path", "") for r in trading_accounts.router.routes
    )

    src_ue = inspect.getsource(__import__("app.services.trading_keys.user_executor", fromlist=["get_user_executor"]).get_user_executor)
    results["user_executor_logs_routing"] = "provider_type=pref" in src_ue

    # Executor wiring
    from app.services import execution

    src = inspect.getsource(execution.adapter._execute_maneuver_in_session)
    results["maneuver_uses_user_executor"] = "get_user_executor" in src

    from app.services.orders import service as order_service

    src2 = inspect.getsource(order_service.submit_manual_order)
    results["manual_order_uses_user_executor"] = "get_user_executor" in src2

    from app.services.portfolio import metrics

    src3 = inspect.getsource(metrics.build_portfolio_metrics)
    results["metrics_uses_user_alpaca"] = "_alpaca_metrics_for_user" in src3

    # HTTP checks via curl inside container
    results["status_endpoint"] = run(
        "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/api/v1/trading-accounts/status"
    )
    results["fallback_endpoint"] = run(
        "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/api/v1/trading-accounts/tokenized/fallback-status"
    )
    results["terminal_snapshot"] = run(
        "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/api/v1/terminal/snapshot"
    )

    print(json.dumps(results, indent=2))
    ok = all(
        [
            results["invalid_key_rejected"],
            results["maneuver_uses_user_executor"],
            results["manual_order_uses_user_executor"],
            results["has_fallback_route"],
            results["user_executor_logs_routing"],
            results["status_endpoint"] == "401",
            results["fallback_endpoint"] == "401",
            results["terminal_snapshot"] == "200",
        ]
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
