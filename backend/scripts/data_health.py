#!/usr/bin/env python3
"""Find every screen-feeding API that answers with an error or «нет данных».

Runs inside the backend container against the live app, as a real account:
  docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T backend \
      python scripts/data_health.py admin@example.com [--ticker NVDA] [--json]

Calls every GET route without path parameters (plus ticker routes with --ticker),
so nothing is written. Prints a table: status, count of «нет данных»/null-ish
markers, time, route. Use it after each deploy to see what is still empty.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
from sqlalchemy import select

from app.core.security import create_access_token
from app.db.models import User
from app.db.session import AsyncSessionLocal

NO_DATA = re.compile(r"нет данных|no[_ ]data|not_configured|unavailable", re.IGNORECASE)
SKIP = re.compile(
    r"/(auth|admin/|ops/fincept|webhooks?|stream|ws|sse|export|pdf|download|telegram|email|oauth|authorize|callback|"
    r"metrics$|health/live|docs|openapi|redoc)",
    re.IGNORECASE,
)


async def _token(email: str) -> str:
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == email.lower()))).scalar_one_or_none()
        if user is None:
            raise SystemExit(f"No user {email}. Create it with scripts/create_user.py first.")
        role = user.role.value if hasattr(user.role, "value") else str(user.role)
        return create_access_token(
            user.email, extra_claims={"is_admin": role == "admin", "role": role, "user_id": user.id}
        )


async def main(email: str, ticker: str, as_json: bool, base: str, timeout: float = 20.0) -> int:
    token = await _token(email)
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(base_url=base, headers=headers, timeout=timeout) as client:
        # Route list straight from the app (the public /openapi.json is off in production).
        from app.main import app as fastapi_app

        spec = fastapi_app.openapi()
        paths: list[str] = []
        for path, ops in (spec.get("paths") or {}).items():
            if "get" not in ops or SKIP.search(path):
                continue
            if "{" in path:
                if re.fullmatch(r".*\{(ticker|symbol)\}.*", path) and path.count("{") == 1:
                    path = re.sub(r"\{(ticker|symbol)\}", ticker, path)
                else:
                    continue
            paths.append(path)

        sem = asyncio.Semaphore(3)  # gentle: do not starve real users of the 2 workers
        rows: list[dict] = []

        async def probe(path: str) -> None:
            async with sem:
                t0 = time.perf_counter()
                try:
                    r = await client.get(path)
                    body = r.text
                    rows.append(
                        {
                            "path": path,
                            "status": r.status_code,
                            "no_data": len(NO_DATA.findall(body)),
                            "bytes": len(body),
                            "ms": int((time.perf_counter() - t0) * 1000),
                        }
                    )
                except httpx.TimeoutException:
                    rows.append({"path": path, "status": "TIME", "no_data": 0, "bytes": 0, "ms": int((time.perf_counter() - t0) * 1000)})
                except Exception as exc:  # noqa: BLE001
                    rows.append({"path": path, "status": "ERR", "no_data": 0, "bytes": 0, "ms": 0, "error": str(exc)[:80]})

        await asyncio.gather(*(probe(p) for p in sorted(set(paths))))

    def bad(row: dict) -> bool:
        return row["status"] != 200 or row["no_data"] > 0

    rows.sort(key=lambda r: (not bad(r), str(r["status"]) == "200", -r["no_data"], r["path"]))
    if as_json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return 0
    broken = [r for r in rows if bad(r)]
    print(f"Проверено {len(rows)} адресов, проблемных {len(broken)}:\n")
    print(f"{'код':>4}  {'«нет данных»':>12}  {'мс':>6}  адрес")
    for r in broken:
        print(f"{r['status']!s:>4}  {r['no_data']:>12}  {r['ms']:>6}  {r['path']}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("email")
    ap.add_argument("--ticker", default="NVDA")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--timeout", type=float, default=30.0, help="seconds per request")
    a = ap.parse_args()
    import logging
    import warnings

    warnings.filterwarnings("ignore")
    logging.disable(logging.WARNING)
    raise SystemExit(asyncio.run(main(a.email, a.ticker, a.json, a.base, a.timeout)))
