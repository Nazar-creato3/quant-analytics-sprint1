#!/usr/bin/env python3
"""Apply Bybit ExecutionProvider integration patches on VPS production tree."""
from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"


def _read(rel: str) -> str:
    p = APP / rel
    if not p.exists():
        raise FileNotFoundError(p)
    return p.read_text(encoding="utf-8")


def _write(rel: str, content: str) -> None:
    p = APP / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    print(f"  wrote {rel}")


def patch_validators(content: str) -> str:
    if "validate_bybit_key" in content and "from app.services.trading_keys.bybit_validator" in content:
        return content
    insert = '''
    if v == "bybit":
        from app.services.trading_keys.bybit_validator import validate_bybit_key

        return await validate_bybit_key(
            api_key=credentials.get("api_key", ""),
            api_secret=credentials.get("api_secret", ""),
            base_url=credentials.get("base_url"),
        )
'''
    marker = '    if v == "finam":'
    if marker not in content:
        raise RuntimeError("validators.py: finam marker not found")
    return content.replace(marker, insert + marker, 1)


def patch_trading_accounts(content: str) -> str:
    if '"venue": "bybit"' in content:
        return content
    bybit_card = '''    {
        "venue": "bybit",
        "title": "Bybit — Tokenized US Equities",
        "description": "US-акции в форме токенов (24/7). API Key + Secret, без OAuth.",
        "connection_type": "raw_key",
        "setup_url": "https://www.bybit.com/app/user/api-management",
        "featured": True,
    },
'''
    content = content.replace(
        '_VENUE_CARDS: list[dict[str, Any]] = [\n    {\n        "venue": "binance",',
        '_VENUE_CARDS: list[dict[str, Any]] = [\n' + bybit_card + '    {\n        "venue": "binance",',
    )
    # Demote Alpaca description
    content = content.replace(
        '"title": "Alpaca (US-акции)",\n        "description": "Подключение через OAuth Alpaca — ключ вводить не нужно",',
        '"title": "Alpaca (US-акции)",\n        "description": "Доступно для не-РФ резидентов. OAuth Alpaca — ключ вводить не нужно",',
    )
    if "demo_mode_available" not in content:
        content = content.replace(
            "return TradingAccountsOverviewOut(venues=venues, rotation_reminders=rotation)",
            "return TradingAccountsOverviewOut(venues=venues, rotation_reminders=rotation, demo_mode_available=True)",
        )
    if "featured" in content and 'featured=c.get("featured"' not in content:
        content = content.replace(
            "connected_accounts=by_venue.get(c[\"venue\"], []),",
            'connected_accounts=by_venue.get(c["venue"], []),\n            featured=bool(c.get("featured")),',
        )
    return content


def patch_user_venue_balances(content: str) -> str:
    if 'meta.venue == "bybit"' in content:
        return content
    block = '''        if meta.venue == "bybit":
            from app.services.portfolio.bybit_balances import _bybit_balance_from_creds

            venues.append(await _bybit_balance_from_creds(creds, mode=meta.account_mode))
            continue
'''
    marker = '        if meta.venue == "binance":'
    if marker not in content:
        raise RuntimeError("user_venue_balances: binance marker not found")
    return content.replace(marker, block + marker, 1)


def patch_router(content: str) -> str:
    if "tokenized_equities_router" in content:
        return content
    if "from app.api.v1.endpoints.trading_accounts import router as trading_accounts_router" in content:
        content = content.replace(
            "from app.api.v1.endpoints.trading_accounts import router as trading_accounts_router",
            "from app.api.v1.endpoints.tokenized_equities import router as tokenized_equities_router\n"
            "from app.api.v1.endpoints.trading_accounts import router as trading_accounts_router",
        )
        content = content.replace(
            "api_router.include_router(trading_accounts_router)",
            "api_router.include_router(tokenized_equities_router)\n"
            "api_router.include_router(trading_accounts_router)",
        )
    return content


def patch_config(content: str) -> str:
    additions = []
    if "BYBIT_API_BASE_URL" not in content:
        additions.append('    BYBIT_API_BASE_URL: str = "https://api.bybit.com"')
    if "EXECUTION_SERVER_PUBLIC_IP" not in content:
        additions.append('    EXECUTION_SERVER_PUBLIC_IP: str | None = None')
    if not additions:
        return content
    # Insert before class Config or at end of Settings fields
    marker = "    class Config:"
    if marker in content:
        return content.replace(marker, "\n".join(additions) + "\n\n" + marker, 1)
    return content + "\n" + "\n".join(additions) + "\n"


def patch_frontend_api(content: str) -> str:
    content = content.replace(
        'export type ConnectRawKeyVenue = "binance" | "alpaca" | "tinkoff" | "tbank" | "finam";',
        'export type ConnectRawKeyVenue = "binance" | "bybit" | "alpaca" | "tinkoff" | "tbank" | "finam";',
    )
    if "validate:" not in content or "trading-accounts/validate" not in content:
        insert = '''
  validate: async (body: {
    venue: ConnectRawKeyVenue;
    api_key: string;
    api_secret: string;
    account_mode?: "paper" | "live";
    no_withdrawal_confirmed?: boolean;
    base_url?: string;
  }) => {
    const { data } = await api.post("/trading-accounts/validate", body);
    return data as { ok: boolean; error?: string; account_display?: string };
  },
'''
        content = content.replace(
            "  connectToken: async (body: {",
            insert + "\n  connectToken: async (body: {",
        )
    if "demo_mode_available" not in content:
        content = content.replace(
            "rotation_reminders: TradingAccountOut[] };",
            "rotation_reminders: TradingAccountOut[]; demo_mode_available?: boolean };",
        )
        content = content.replace(
            "connected_accounts: TradingAccountOut[] }>; rotation_reminders",
            "connected_accounts: TradingAccountOut[]; featured?: boolean }>; rotation_reminders",
        )
    return content


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--frontend-root", type=str, default=None)
    args = parser.parse_args()
    patches = [
        ("services/trading_keys/validators.py", patch_validators),
        ("api/v1/endpoints/trading_accounts.py", patch_trading_accounts),
        ("services/portfolio/user_venue_balances.py", patch_user_venue_balances),
        ("api/v1/router.py", patch_router),
        ("core/config.py", patch_config),
    ]
    for rel, fn in patches:
        try:
            original = _read(rel)
            updated = fn(original)
            if updated != original:
                print(f"patch {rel}")
                if args.apply:
                    _write(rel, updated)
            else:
                print(f"skip {rel} (already patched)")
        except FileNotFoundError as exc:
            print(f"WARN missing {exc}")

    if args.frontend_root:
        api_path = Path(args.frontend_root) / "src/lib/api.ts"
        if api_path.exists():
            original = api_path.read_text(encoding="utf-8")
            updated = patch_frontend_api(original)
            if updated != original:
                print("patch frontend/src/lib/api.ts")
                if args.apply:
                    api_path.write_text(updated, encoding="utf-8")
                    print("  wrote frontend/src/lib/api.ts")
        else:
            print(f"WARN missing {api_path}")
    print("done")


if __name__ == "__main__":
    main()
