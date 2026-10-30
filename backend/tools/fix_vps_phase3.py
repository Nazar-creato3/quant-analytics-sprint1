"""Phase 3 — complete Flow A/B separation: maneuvers, conditionals, metrics, market data."""
from __future__ import annotations

from pathlib import Path

BACKEND = Path("/home/user1/myapp/backend")


def patch_use_local_paper(content: str) -> str:
    old = """def use_local_paper_simulation() -> bool:
    \"\"\"Use internal paper fills when live trading is locked or Alpaca keys are absent.\"\"\"
    if settings.live_trading_unlocked:
        return False
    if not settings.PAPER_TRADING_ENABLED:
        return False
    if not settings.ALPACA_API_KEY or not settings.ALPACA_SECRET_KEY:
        return True
    # Default: prefer local instant paper fills for approval-only workflow
    return True"""
    new = """def use_local_paper_simulation() -> bool:
    \"\"\"Paper fills when live is locked — never depends on founder/platform keys.\"\"\"
    if settings.live_trading_unlocked:
        return False
    return bool(settings.PAPER_TRADING_ENABLED)"""
    if old in content:
        return content.replace(old, new)
    return content


def patch_execute_maneuver(content: str) -> str:
    old = """    executor = get_executor()
    order_result = await executor.submit_order(req)"""
    new = """    exec_user_id = maneuver.approved_by
    if not exec_user_id:
        maneuver.status = ManeuverStatus.APPROVED
        await session.commit()
        logger.error("Maneuver missing approved_by — cannot resolve user key", maneuver_id=maneuver_id)
        return
    from app.services.trading_keys.user_executor import (
        TradingKeyRequiredError,
        get_user_executor,
    )

    acct_mode = trading_mode_val if trading_mode_val in ("paper", "live") else "live"
    try:
        executor = await get_user_executor(
            session,
            user_id=exec_user_id,
            ticker=maneuver.ticker,
            account_mode=acct_mode,
        )
    except TradingKeyRequiredError as exc:
        maneuver.status = ManeuverStatus.APPROVED
        await session.commit()
        logger.error("Maneuver execution blocked — no user key", maneuver_id=maneuver_id, error=str(exc))
        return
    order_result = await executor.submit_order(req)"""
    if old in content and "get_user_executor" not in content.split("execute_maneuver")[1][:3000]:
        return content.replace(old, new, 1)
    return content


def patch_conditional_manager(content: str) -> str:
    old = """            executor = get_executor()
            fill = await executor.submit_order(req)"""
    new = """            if not parent.user_id:
                watch.status = "failed"
                continue
            from app.services.trading_keys.user_executor import (
                TradingKeyRequiredError,
                get_user_executor,
            )

            try:
                executor = await get_user_executor(
                    db,
                    user_id=parent.user_id,
                    ticker=watch.ticker,
                )
            except TradingKeyRequiredError:
                watch.status = "failed"
                parent.error_message = "Trading key required — connect venue in Settings"
                continue
            fill = await executor.submit_order(req)"""
    if old in content and "get_user_executor" not in content:
        return content.replace(old, new)
    return content


def patch_metrics(content: str) -> str:
    if "_alpaca_metrics_for_user" in content:
        return content
    old_fn = """async def _alpaca_metrics() -> PortfolioMetricsOut | None:
    if not settings.ALPACA_API_KEY or not settings.ALPACA_SECRET_KEY:
        return None
    if not settings.live_trading_unlocked:
        return None

    try:
        from app.services.execution.adapter import AlpacaExecutor

        executor = AlpacaExecutor()"""
    new_fn = """async def _alpaca_metrics_for_user(
    db: AsyncSession,
    user_id: str,
) -> PortfolioMetricsOut | None:
    if not settings.live_trading_unlocked:
        return None

    try:
        from app.services.execution.adapter import AlpacaExecutor
        from app.services.trading_keys.resolver import UserTradingKeyNotFound, get_active_user_credentials

        creds_row = await get_active_user_credentials(
            db,
            user_id=user_id,
            venue="alpaca",
            account_mode="live",
            action="portfolio_metrics",
        )
        payload = creds_row.credentials
        base = payload.get("base_url") or "https://api.alpaca.markets"
        executor = AlpacaExecutor(
            api_key=payload.get("api_key", ""),
            api_secret=payload.get("api_secret", ""),
            base_url=base,
            is_live=True,
        )"""
    if old_fn not in content:
        return content
    content = content.replace(old_fn, new_fn)
    content = content.replace(
        """    except Exception as exc:
        logger.warning("Alpaca portfolio metrics unavailable", error=str(exc))
        return None""",
        """    except UserTradingKeyNotFound:
        return None
    except Exception as exc:
        logger.warning("Alpaca portfolio metrics unavailable", error=str(exc))
        return None""",
        1,
    )
    old_build = """async def build_portfolio_metrics(
    email: str,
    db: AsyncSession,
    *,
    price_overrides: dict[str, float] | None = None,
) -> PortfolioMetricsOut:
    \"\"\"Return live portfolio metrics; Alpaca when live, else internal paper aggregation.\"\"\"
    live = await _alpaca_metrics()
    if live is not None:
        return live
    return await _internal_metrics(email, db, price_overrides=price_overrides)"""
    new_build = """async def build_portfolio_metrics(
    email: str,
    db: AsyncSession,
    *,
    price_overrides: dict[str, float] | None = None,
) -> PortfolioMetricsOut:
    \"\"\"Return live portfolio metrics from user's Alpaca key when live, else internal paper.\"\"\"
    from app.services.portfolio.user_scope import get_user_by_email

    user = await get_user_by_email(db, email)
    if user and settings.live_trading_unlocked:
        live = await _alpaca_metrics_for_user(db, user.id)
        if live is not None:
            return live
    return await _internal_metrics(email, db, price_overrides=price_overrides)"""
    return content.replace(old_build, new_build)


def patch_market_data_client(content: str) -> str:
    if "platform_keys.alpaca_data_headers" in content:
        return content
    content = content.replace(
        "from app.core.config import settings",
        "from app.core.config import settings\nfrom app.services.trading_keys import platform_keys",
        1,
    )
    content = content.replace(
        """        self._headers = {
            "APCA-API-KEY-ID": settings.ALPACA_API_KEY,
            "APCA-API-SECRET-KEY": settings.ALPACA_SECRET_KEY,
        }""",
        """        self._headers = {
            **platform_keys.alpaca_data_headers(),
            "Content-Type": "application/json",
        }""",
        1,
    )
    return content


def patch_recent_trades(content: str) -> str:
    if "platform_keys" in content:
        return content
    content = content.replace(
        "from app.core.config import settings",
        "from app.core.config import settings\nfrom app.services.trading_keys import platform_keys",
        1,
    )
    content = content.replace(
        """        "APCA-API-KEY-ID": settings.ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": settings.ALPACA_SECRET_KEY,""",
        "**platform_keys.alpaca_data_headers(),",
        1,
    )
    return content


def patch_ops_refresh(content: str) -> str:
    old = """@router.post("/refresh-venue-balances", response_model=VenueBalancesOut)
async def refresh_venue_balances_endpoint(
    payload: dict = Depends(get_current_user_payload),
) -> VenueBalancesOut:
    \"\"\"Recompute per-venue balances and refresh the ops cache. Authenticated operator action.\"\"\"
    balances = await build_venue_balances()"""
    new = """@router.post("/refresh-venue-balances", response_model=VenueBalancesOut)
async def refresh_venue_balances_endpoint(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> VenueBalancesOut:
    \"\"\"Recompute per-venue balances from the user's keys and refresh ops cache.\"\"\"
    from app.services.portfolio.user_scope import get_user_by_email
    from app.services.portfolio.user_venue_balances import build_user_venue_balances

    user = await get_user_by_email(db, email)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    balances = await build_user_venue_balances(db, user.id)"""
    if old not in content:
        return content
    content = content.replace(old, new)
    if "build_venue_balances" in content and "user_venue_balances" not in content.split("build_venue_balances")[0][-200:]:
        content = content.replace(
            "from app.services.portfolio.venue_balances import build_venue_balances\n",
            "",
        )
    return content


def main() -> None:
    patches = {
        BACKEND / "app/services/orders/conditional_manager.py": patch_conditional_manager,
        BACKEND / "app/services/portfolio/metrics.py": patch_metrics,
        BACKEND / "app/services/market_data/client.py": patch_market_data_client,
        BACKEND / "app/services/orders/recent_trades.py": patch_recent_trades,
        BACKEND / "app/api/v1/endpoints/ops.py": patch_ops_refresh,
    }
    # adapter needs combined patch
    adapter_path = BACKEND / "app/services/execution/adapter.py"
    if adapter_path.exists():
        t = adapter_path.read_text(encoding="utf-8")
        u = patch_execute_maneuver(patch_use_local_paper(t))
        if u != t:
            adapter_path.write_text(u, encoding="utf-8")
            print("PATCHED app/services/execution/adapter.py")

    for path, fn in patches.items():
        if path == adapter_path:
            continue
        if not path.exists():
            print("SKIP", path)
            continue
        original = path.read_text(encoding="utf-8")
        updated = fn(original)
        if updated != original:
            path.write_text(updated, encoding="utf-8")
            print("PATCHED", path.relative_to(BACKEND))
        else:
            print("OK", path.relative_to(BACKEND))


if __name__ == "__main__":
    main()
