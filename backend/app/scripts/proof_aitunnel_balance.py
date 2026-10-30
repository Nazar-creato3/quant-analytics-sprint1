"""Proof script: AITUNNEL balance check wired into hourly health reporter."""
from __future__ import annotations

import asyncio
import json
import sys


async def main() -> int:
    from app.services.health.reporter import check_aitunnel_token_balance, run_health_report
    from app.services.llm.aitunnel_balance import assess_balance, fetch_balance_snapshot

    print("=== AITUNNEL balance snapshot (API) ===")
    try:
        snap = await fetch_balance_snapshot()
        print(json.dumps({
            "balance_rub": snap.balance_rub,
            "budget_rub": snap.budget_rub,
            "effective_rub": snap.effective_rub,
            "source": snap.source,
        }, ensure_ascii=False, indent=2))
    except Exception as exc:
        print(f"balance API error: {exc}")

    print("\n=== assess_balance() ===")
    verdict = await assess_balance()
    print(json.dumps(verdict, ensure_ascii=False, indent=2))

    print("\n=== check_aitunnel_token_balance() (health row) ===")
    row = await check_aitunnel_token_balance()
    print(json.dumps(row, ensure_ascii=False, indent=2))

    print("\n=== run_health_report (telegram off) — aitunnel row included ===")
    report = await run_health_report(send_telegram=False)
    names = [r.get("name") for r in report.get("results", [])]
    print("checks:", names)
    aitunnel_rows = [r for r in report.get("results", []) if r.get("name") == "aitunnel_token_balance"]
    print(json.dumps(aitunnel_rows, ensure_ascii=False, indent=2))

    wired = "aitunnel_token_balance" in names
    print("\nPROOF:", "WIRED" if wired else "NOT WIRED")
    return 0 if wired else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
