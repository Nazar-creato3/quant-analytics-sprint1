from pathlib import Path

p = Path("/home/user1/myapp/backend/app/api/v1/endpoints/portfolio.py")
text = p.read_text(encoding="utf-8")
old = """@router.get("/balances", response_model=VenueBalancesOut)
async def get_venue_balances(
    email: str = Depends(get_current_user_email),
    _paid: object = Depends(require_paid_subscription),
) -> VenueBalancesOut:
    \"\"\"Per-venue balances (Binance testnet live, Finam/Tinkoff stub) + aggregated total.\"\"\"
    return await build_venue_balances()"""
new = """@router.get("/balances", response_model=VenueBalancesOut)
async def get_venue_balances(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
    _paid: object = Depends(require_paid_subscription),
) -> VenueBalancesOut:
    \"\"\"Per-venue balances from the user's connected trading keys (Flow B).\"\"\"
    user = await get_user_by_email(db, email)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return await build_user_venue_balances(db, user.id)"""
if old not in text:
    raise SystemExit("portfolio block not found")
p.write_text(text.replace(old, new), encoding="utf-8")
print("portfolio.py fixed")

# http_providers platform keys
hp = Path("/home/user1/myapp/backend/app/services/market_data/http_providers.py")
ht = hp.read_text(encoding="utf-8")
if "platform_keys" not in ht:
    ht = ht.replace(
        "from app.core.config import settings",
        "from app.core.config import settings\nfrom app.services.trading_keys import platform_keys",
        1,
    )
    ht = ht.replace(
        "_usable(settings.ALPACA_API_KEY) and _usable(settings.ALPACA_SECRET_KEY)",
        "platform_keys.platform_key_configured('ALPACA_API_KEY') and platform_keys.platform_key_configured('ALPACA_SECRET_KEY')",
        1,
    )
    hp.write_text(ht, encoding="utf-8")
    print("http_providers.py patched")

# order_book missing import
ob = Path("/home/user1/myapp/backend/app/services/orders/order_book.py")
obt = ob.read_text(encoding="utf-8")
if "import platform_keys" not in obt and "platform_keys.alpaca_data_headers" in obt:
    obt = obt.replace(
        "from app.utils.secret_redact import redact_secrets",
        "from app.utils.secret_redact import redact_secrets\n    from app.services.trading_keys import platform_keys",
        1,
    )
    ob.write_text(obt, encoding="utf-8")
    print("order_book import fixed")
