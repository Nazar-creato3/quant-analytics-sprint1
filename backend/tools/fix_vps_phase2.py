"""Phase 2 patches: user executor wiring, celery beat."""
from __future__ import annotations

from pathlib import Path

BACKEND = Path("/home/user1/myapp/backend")


def patch_alpaca_executor(content: str) -> str:
    old = """    def __init__(self) -> None:
        self._is_live = settings.live_trading_unlocked
        self._base_url = self.LIVE_URL if self._is_live else self.PAPER_URL
        self._headers = {
            "APCA-API-KEY-ID": settings.ALPACA_API_KEY,
            "APCA-API-SECRET-KEY": settings.ALPACA_SECRET_KEY,
            "Content-Type": "application/json",
        }"""
    new = """    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_secret: str | None = None,
        base_url: str | None = None,
        is_live: bool | None = None,
    ) -> None:
        self._is_live = is_live if is_live is not None else settings.live_trading_unlocked
        if base_url:
            root = base_url.rstrip("/")
            self._base_url = root if root.endswith("/v2") else f"{root}/v2"
        else:
            self._base_url = self.LIVE_URL if self._is_live else self.PAPER_URL
        key = (api_key or settings.ALPACA_API_KEY or "").strip()
        secret = (api_secret or settings.ALPACA_SECRET_KEY or "").strip()
        self._headers = {
            "APCA-API-KEY-ID": key,
            "APCA-API-SECRET-KEY": secret,
            "Content-Type": "application/json",
        }"""
    if old in content:
        return content.replace(old, new)
    return content


def patch_tinkoff_executor(content: str) -> str:
    marker = '    """Submit MOEX spot orders (equities + currency) via T-Bank Invest REST API."""\n'
    if "_token_override" not in content and marker in content:
        content = content.replace(
            marker,
            marker + "\n    def __init__(self, token: str | None = None) -> None:\n"
            "        self._token_override = token\n",
        )
    old_token = "        token = _tinkoff_token()"
    new_token = "        token = self._token_override or _tinkoff_token()"
    if old_token in content and new_token not in content:
        content = content.replace(old_token, new_token, 1)
    return content


def patch_submit_manual_order(content: str) -> str:
    old = """    executor = get_executor()
    result = await executor.submit_order(req)"""
    new = """    if not user_id:
        raise ValueError("Authentication required for order execution")
    from app.services.trading_keys.user_executor import (
        TradingKeyRequiredError,
        get_user_executor,
    )

    try:
        executor = await get_user_executor(db, user_id=user_id, ticker=order.ticker)
    except TradingKeyRequiredError as exc:
        order.status = "rejected"
        order.error_message = str(exc)
        order.submitted_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(order)
        raise ValueError(str(exc)) from exc
    result = await executor.submit_order(req)"""
    if old in content and "get_user_executor" not in content:
        return content.replace(old, new)
    return content


def patch_celery_beat(content: str) -> str:
    entry = '''        "trading-key-health-daily": {
            "task": "app.tasks.trading_keys.daily_trading_key_health_check",
            "schedule": crontab(minute=0, hour=6),
            "options": {"queue": "pipeline"},
        },
'''
    if "trading-key-health-daily" in content:
        return content
    anchor = '        "grid-bot-tick-every-minute": {'
    return content.replace(anchor, entry + anchor)


def main() -> None:
    patches = {
        BACKEND / "app/services/execution/adapter.py": patch_alpaca_executor,
        BACKEND / "app/services/broker/tinkoff_orders.py": patch_tinkoff_executor,
        BACKEND / "app/services/orders/service.py": patch_submit_manual_order,
        BACKEND / "app/tasks/celery_app.py": patch_celery_beat,
    }
    for path, fn in patches.items():
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
