"""Deploy integration patches for trading keys architecture.

Run on VPS from repo root after copying new files:
  python backend/tools/apply_trading_keys_patches.py --check
  python backend/tools/apply_trading_keys_patches.py --apply
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"


def patch_router(content: str) -> str:
    if "trading_accounts" in content:
        return content
    content = content.replace(
        "from app.api.v1.endpoints.trading import router as trading_router",
        "from app.api.v1.endpoints.trading import router as trading_router\n"
        "from app.api.v1.endpoints.trading_accounts import router as trading_accounts_router",
    )
    content = content.replace(
        "api_router.include_router(trading_router)",
        "api_router.include_router(trading_router)\n"
        "api_router.include_router(trading_accounts_router)",
    )
    return content


def patch_order_book(content: str) -> str:
    if "platform_keys" in content:
        return content
    content = content.replace(
        "from app.core.config import settings",
        "from app.services.trading_keys import platform_keys",
        1,
    )
    content = re.sub(
        r'"APCA-API-KEY-ID": settings\.ALPACA_API_KEY,\s*\n\s*"APCA-API-SECRET-KEY": settings\.ALPACA_SECRET_KEY,',
        '**platform_keys.alpaca_data_headers(),',
        content,
        count=1,
    )
    return content


def patch_portfolio(content: str) -> str:
    if "build_user_venue_balances" in content:
        return content
    content = content.replace(
        "from app.services.portfolio.venue_balances import build_venue_balances",
        "from app.services.portfolio.user_venue_balances import build_user_venue_balances\n"
        "from app.services.portfolio.user_scope import get_user_by_email",
    )
    content = re.sub(
        r"async def get_venue_balances\(\s*\n\s*email: str = Depends\(get_current_user_email\),\s*\n\s*\) -> VenueBalancesOut:\s*\n\s*return await build_venue_balances\(\)",
        """async def get_venue_balances(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> VenueBalancesOut:
    user = await get_user_by_email(db, email)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return await build_user_venue_balances(db, user.id)""",
        content,
    )
    if "get_user_db" not in content:
        content = content.replace(
            "from app.core.deps import get_current_user_email",
            "from app.core.deps import get_current_user_email, get_user_db",
        )
    if "AsyncSession" not in content:
        content = "from sqlalchemy.ext.asyncio import AsyncSession\n" + content
    if "HTTPException" not in content:
        content = content.replace(
            "from fastapi import APIRouter",
            "from fastapi import APIRouter, HTTPException",
        )
    return content


def patch_config(content: str) -> str:
    additions = []
    if "ALPACA_OAUTH_CLIENT_ID" not in content:
        additions.append('    ALPACA_OAUTH_CLIENT_ID: str = ""')
        additions.append('    ALPACA_OAUTH_CLIENT_SECRET: str = ""')
        additions.append('    ALPACA_OAUTH_REDIRECT_URI: str = ""')
        additions.append('    FRONTEND_BASE_URL: str = "http://localhost:3000"')
    if additions:
        marker = "    ALPACA_BASE_URL:"
        content = content.replace(
            marker,
            "\n".join(additions) + "\n\n" + marker,
            1,
        )
    return content


PATCHES = {
    APP / "api/v1/router.py": patch_router,
    APP / "services/orders/order_book.py": patch_order_book,
    APP / "api/v1/endpoints/portfolio.py": patch_portfolio,
    APP / "core/config.py": patch_config,
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for path, fn in PATCHES.items():
        if not path.exists():
            print(f"SKIP missing {path}")
            continue
        original = path.read_text(encoding="utf-8")
        updated = fn(original)
        if original == updated:
            print(f"OK already patched {path.relative_to(ROOT)}")
        elif args.check:
            print(f"NEEDS PATCH {path.relative_to(ROOT)}")
        elif args.apply:
            path.write_text(updated, encoding="utf-8")
            print(f"PATCHED {path.relative_to(ROOT)}")
        else:
            print(f"DRY-RUN would patch {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
