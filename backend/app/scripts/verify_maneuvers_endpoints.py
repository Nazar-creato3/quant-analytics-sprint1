"""Prompt 90: dump raw JSON from analysis poll + report + pending list (same run)."""
from __future__ import annotations

import asyncio
import json
import sys
import uuid

from sqlalchemy import desc, select
from sqlalchemy.orm import selectinload

from app.db.models import Maneuver, ManeuverReport
from app.db.session import AsyncSessionLocal
from app.services.pipeline.maneuver_counts import count_tradeable_persisted


def _status_str(m: Maneuver) -> str:
    return m.status.value if hasattr(m.status, "value") else str(m.status)


def _pending_tradeable(maneuvers: list) -> int:
    pending = [m for m in maneuvers if _status_str(m).startswith("pending")]
    return count_tradeable_persisted(pending)


async def main() -> int:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ManeuverReport)
            .options(selectinload(ManeuverReport.maneuvers))
            .order_by(desc(ManeuverReport.created_at))
            .limit(1)
        )
        report = result.scalar_one_or_none()
        if not report:
            print(json.dumps({"error": "no_maneuver_reports_in_db"}, ensure_ascii=False))
            return 1

        ctx = report.market_context if isinstance(report.market_context, dict) else {}
        poll_like = {
            "run_id": report.pipeline_run_id or str(uuid.uuid4()),
            "status": "complete",
            "report_id": str(report.id),
            "tradeable_count": ctx.get("tradeable_count"),
            "maneuver_slots": ctx.get("maneuver_slots"),
            "tickers_analyzed": ctx.get("tickers_analyzed"),
        }
        report_json = {
            "id": str(report.id),
            "maneuver_count": len(report.maneuvers),
            "tradeable_persisted": count_tradeable_persisted(report.maneuvers),
            "market_context_tradeable": ctx.get("tradeable_count"),
            "maneuvers_summary": [
                {
                    "rank": m.rank,
                    "ticker": m.ticker,
                    "strategy_type": m.strategy_type.value
                    if hasattr(m.strategy_type, "value")
                    else str(m.strategy_type),
                    "direction": m.direction,
                    "status": m.status.value if hasattr(m.status, "value") else str(m.status),
                }
                for m in sorted(report.maneuvers, key=lambda x: x.rank)
            ],
        }
        pending = [m for m in report.maneuvers if _status_str(m).startswith("pending")]
        list_like = {
            "items_count": len(pending),
            "pending_tradeable_count": _pending_tradeable(report.maneuvers),
            "tradeable_in_report": count_tradeable_persisted(report.maneuvers),
            "items": [
                {
                    "id": str(m.id),
                    "ticker": m.ticker,
                    "strategy_type": m.strategy_type.value
                    if hasattr(m.strategy_type, "value")
                    else str(m.strategy_type),
                    "status": m.status.value if hasattr(m.status, "value") else str(m.status),
                }
                for m in pending[:20]
            ],
        }
        out = {
            "STEP1_poll_status_equivalent": poll_like,
            "STEP2_report_GET_equivalent": report_json,
            "STEP2_pending_list_equivalent": list_like,
            "STEP3_poll_matches_report": poll_like.get("tradeable_count")
            == report_json["tradeable_persisted"],
            "STEP3_toast_pending_honest": list_like["pending_tradeable_count"]
            <= report_json["tradeable_persisted"],
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
        sync_ok = out["STEP3_poll_matches_report"] and out["STEP3_toast_pending_honest"]
        return 0 if sync_ok else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
