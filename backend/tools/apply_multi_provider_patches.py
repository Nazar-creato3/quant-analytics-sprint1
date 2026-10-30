#!/usr/bin/env python3
"""Apply multi-provider tokenized equity patches on VPS."""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"


def _read(rel: str) -> str:
    return (APP / rel).read_text(encoding="utf-8")


def _write(rel: str, content: str) -> None:
    p = APP / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    print(f"  wrote {rel}")


def patch_service(content: str) -> str:
    if "provider_type: str | None = None" in content:
        return content
    content = content.replace(
        "    no_withdrawal_confirmed: bool = False,\n) -> tuple[TradingKeyMetadataORM | None, ValidationResult]:",
        "    no_withdrawal_confirmed: bool = False,\n    provider_type: str | None = None,\n) -> tuple[TradingKeyMetadataORM | None, ValidationResult]:",
    )
    old = '    venue_norm = venue.lower()\n    if venue_norm in ("binance", "finam", "tinkoff", "tbank") and not no_withdrawal_confirmed:'
    new = '''    venue_norm = venue.lower()
    from app.services.execution.tokenized_provider_type import TOKENIZED_EQUITY_VENUE, TokenizedProvider

    if venue_norm in ("bybit", "mexc"):
        venue_norm = TOKENIZED_EQUITY_VENUE
    pt = TokenizedProvider.normalize(provider_type or venue).value if venue_norm == TOKENIZED_EQUITY_VENUE else None
    if venue_norm in ("binance", "finam", "tinkoff", "tbank", TOKENIZED_EQUITY_VENUE) and not no_withdrawal_confirmed:'''
    content = content.replace(old, new)
    if '"provider_type": pt' not in content:
        content = content.replace(
            "    validation = await validate_venue_credentials(venue_norm, credentials, account_mode=account_mode)",
            "    credentials = {**credentials, **({'provider_type': pt} if pt else {})}\n"
            "    validation = await validate_venue_credentials(\n"
            "        venue_norm, credentials, account_mode=account_mode, provider_type=pt\n"
            "    )",
        )
    if "existing.provider_type" not in content:
        content = content.replace(
            "        existing.account_display = validation.account_display",
            "        existing.provider_type = pt\n        existing.account_display = validation.account_display",
        )
        content = content.replace(
            "            account_display=validation.account_display,\n            rotation_due_at=now + timedelta(days=ROTATION_DAYS),",
            "            provider_type=pt,\n            account_display=validation.account_display,\n            rotation_due_at=now + timedelta(days=ROTATION_DAYS),",
        )
    return content


def patch_validators(content: str) -> str:
    if "TOKENIZED_EQUITY_VENUE" in content and "validate_mexc_key" in content:
        return content
    if "provider_type: str | None = None" not in content:
        content = content.replace(
            "    account_mode: str = \"live\",\n) -> ValidationResult:",
            "    account_mode: str = \"live\",\n    provider_type: str | None = None,\n) -> ValidationResult:",
        )
    block = '''
    from app.services.execution.tokenized_provider_type import TOKENIZED_EQUITY_VENUE, TokenizedProvider

    if v == TOKENIZED_EQUITY_VENUE or v in ("bybit", "mexc"):
        pt = TokenizedProvider.normalize(provider_type or credentials.get("provider_type") or v).value
        if pt == "mexc":
            from app.services.trading_keys.mexc_validator import validate_mexc_key

            return await validate_mexc_key(
                api_key=credentials.get("api_key", ""),
                api_secret=credentials.get("api_secret", ""),
                base_url=credentials.get("base_url"),
            )
        from app.services.trading_keys.bybit_validator import validate_bybit_key

        return await validate_bybit_key(
            api_key=credentials.get("api_key", ""),
            api_secret=credentials.get("api_secret", ""),
            base_url=credentials.get("base_url"),
        )
'''
    marker = '    if v == "finam":'
    if marker in content and "TOKENIZED_EQUITY_VENUE" not in content:
        content = content.replace(marker, block + marker, 1)
    return content


def patch_trading_accounts_ep(content: str) -> str:
    if "tokenized_equity" in content and "provider_options" in content:
        return content
    tokenized_card = '''    {
        "venue": "tokenized_equity",
        "title": "Tokenized US Equities",
        "description": "Bybit (primary) or MEXC (alternate). Connect API key for your chosen provider only.",
        "connection_type": "raw_key",
        "setup_url": "https://www.bybit.com/app/user/api-management",
        "featured": True,
        "provider_options": ["bybit", "mexc"],
    },
'''
    if '"venue": "bybit"' in content:
        import re
        content = re.sub(
            r'\s*\{\s*"venue": "bybit",.*?\},\n',
            "\n" + tokenized_card,
            content,
            count=1,
            flags=re.DOTALL,
        )
    elif '"venue": "tokenized_equity"' not in content:
        content = content.replace(
            '_VENUE_CARDS: list[dict[str, Any]] = [\n    {\n        "venue": "binance",',
            '_VENUE_CARDS: list[dict[str, Any]] = [\n' + tokenized_card + '    {\n        "venue": "binance",',
        )
    if "provider_type=row.provider_type" not in content:
        content = content.replace(
            "        venue=row.venue,",
            "        venue=row.venue,\n        provider_type=getattr(row, \"provider_type\", None),",
        )
    if "TokenizedFallbackOut" not in content:
        fallback_ep = '''

@router.get("/tokenized/fallback-status", response_model=TokenizedFallbackOut)
async def tokenized_fallback_status(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> TokenizedFallbackOut:
    from app.services.trading_keys.tokenized_fallback import check_tokenized_fallback

    user = await _require_user(db, email)
    return await check_tokenized_fallback(db, user_id=user.id, email=email)
'''
        content = content.replace(
            "from app.schemas.trading_accounts import (",
            "from app.schemas.trading_accounts import (\n    TokenizedFallbackOut,",
        )
        if "@router.get(\"/tokenized/fallback-status\"" not in content:
            content = content + fallback_ep
    if "body.provider_type" not in content:
        content = content.replace(
            "        no_withdrawal_confirmed=body.no_withdrawal_confirmed,\n    )",
            "        no_withdrawal_confirmed=body.no_withdrawal_confirmed,\n        provider_type=body.provider_type,\n    )",
            1,
        )
    return content


def patch_user_venue_balances(content: str) -> str:
    if "tokenized_balance_from_creds" in content:
        return content
    block = '''        if meta.venue in ("tokenized_equity", "bybit", "mexc"):
            from app.services.portfolio.tokenized_balances import tokenized_balance_from_creds

            pt = getattr(meta, "provider_type", None) or creds.get("provider_type") or meta.venue
            if pt in ("bybit", "mexc", "tokenized_equity"):
                pt = "bybit" if pt in ("bybit", "tokenized_equity") and creds.get("provider_type") is None else pt
            if pt == "bybit" and creds.get("provider_type") == "mexc":
                pt = "mexc"
            pt = creds.get("provider_type") or getattr(meta, "provider_type", None) or ("mexc" if meta.venue == "mexc" else "bybit")
            venues.append(await tokenized_balance_from_creds(creds, mode=meta.account_mode, provider_type=pt))
            continue
'''
    marker = '        if meta.venue == "bybit":'
    if marker in content:
        content = content.replace(marker, block, 1)
        # remove old bybit block if duplicated
        old = '''        if meta.venue == "bybit":
            from app.services.portfolio.bybit_balances import _bybit_balance_from_creds

            venues.append(await _bybit_balance_from_creds(creds, mode=meta.account_mode))
            continue
'''
        content = content.replace(old, "")
    elif 'meta.venue == "binance"' in content:
        content = content.replace(
            '        if meta.venue == "binance":',
            block + '\n        if meta.venue == "binance":',
            1,
        )
    return content


def patch_settings_schema(content: str) -> str:
    if "tokenized_equity_provider" in content:
        return content
    content = content.replace(
        "    live_trading_enabled: bool = False\n",
        "    live_trading_enabled: bool = False\n    tokenized_equity_provider: str = \"bybit\"\n",
    )
    content = content.replace(
        "    default_watchlist: Optional[list[str]] = None\n",
        "    default_watchlist: Optional[list[str]] = None\n    tokenized_equity_provider: Optional[str] = None\n",
    )
    return content


def patch_settings_defaults(content: str) -> str:
    if "tokenized_equity_provider" in content:
        return content
    return content.replace(
        '        "live_trading_enabled": settings.live_trading_unlocked,\n    }',
        '        "live_trading_enabled": settings.live_trading_unlocked,\n        "tokenized_equity_provider": "bybit",\n    }',
    )


def patch_config(content: str) -> str:
    adds = []
    if "MEXC_API_BASE_URL" not in content:
        adds.append('    MEXC_API_BASE_URL: str = "https://api.mexc.com"')
    if not adds:
        return content
    needle = "    BYBIT_API_BASE_URL:"
    if needle in content:
        return content.replace(
            needle,
            "\n".join(adds) + "\n    " + needle.lstrip(),
            1,
        )
    return content + "\n" + "\n".join(adds) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    patches = [
        ("services/trading_keys/service.py", patch_service),
        ("services/trading_keys/validators.py", patch_validators),
        ("api/v1/endpoints/trading_accounts.py", patch_trading_accounts_ep),
        ("services/portfolio/user_venue_balances.py", patch_user_venue_balances),
        ("schemas/schemas.py", patch_settings_schema),
        ("api/v1/endpoints/settings.py", patch_settings_defaults),
        ("core/config.py", patch_config),
    ]
    for rel, fn in patches:
        try:
            orig = _read(rel)
            upd = fn(orig)
            if upd != orig:
                print(f"patch {rel}")
                if args.apply:
                    _write(rel, upd)
        except FileNotFoundError as exc:
            print(f"WARN {exc}")
    print("done")


if __name__ == "__main__":
    main()
