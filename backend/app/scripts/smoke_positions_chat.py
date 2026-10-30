"""One-shot prod smoke: open positions enrichment + chat ask-ai."""
from __future__ import annotations

import asyncio
import json
import os

import httpx

from app.core.security import create_access_token


async def main() -> None:
    email = os.environ.get("SMOKE_EMAIL", "user@example.com")
    token = create_access_token(email)
    headers = {"Authorization": f"Bearer {token}"}
    base = "http://127.0.0.1:8000/api/v1"
    out: dict = {}

    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.get(
            f"{base}/maneuvers",
            headers=headers,
            params={"status": "approved,filled,executing", "page_size": 10},
        )
        body = r.json()
        out["maneuvers"] = {
            "status": r.status_code,
            "items": [
                {
                    "ticker": m.get("ticker"),
                    "current_price": m.get("current_price"),
                    "stop_loss": m.get("stop_loss"),
                    "take_profit": m.get("take_profit"),
                    "unrealized_pnl": m.get("unrealized_pnl"),
                    "approx_profit": m.get("approx_profit"),
                    "expected_pnl_low": m.get("expected_pnl_low"),
                    "tp_hit_probability": m.get("tp_hit_probability"),
                }
                for m in body.get("items") or []
            ],
        }

        cr = await client.post(f"{base}/chat/conversations/ticker/AMZN", headers=headers)
        conv = cr.json()
        cid = conv.get("id")
        out["chat_conv"] = {"status": cr.status_code, "id": cid}
        if cid:
            ar = await client.post(
                f"{base}/chat/conversations/{cid}/ask-ai",
                headers=headers,
                json={"body": "AMZN краткий прогноз на неделю"},
            )
            payload = ar.json() if ar.headers.get("content-type", "").startswith("application/json") else {}
            advisor = payload.get("advisor_message") or {}
            out["chat_ask"] = {
                "status": ar.status_code,
                "advisor_preview": (advisor.get("body") or str(payload))[:240],
            }

    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
