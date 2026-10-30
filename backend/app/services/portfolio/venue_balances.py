"""Multi-venue balance aggregator.

Reports per-venue capital (trading / balance / total) plus a grand total for
the cockpit. Credentials are read from ``backend/.env`` (same pattern as the
ops pilot-status view). Every venue is best-effort: a missing key or network
failure yields a ``configured``/``pending`` row with a detail message instead
of raising.

Venue support today:
* **binance** — live signed ``/api/v3/account`` call against the configured
  base URL (Spot testnet in staging). USD figures are the stablecoin
  (USDT/USDC/…) free (balance) and locked (trading) totals.
* **finam** / **tinkoff** — platform keys only feed market data. Orders and
  balances always use each user's own key (see ``user_venue_balances``), so
  these rows report the market-data key state, never a platform balance.

No secrets are logged.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.core.logging import get_logger
from app.schemas.portfolio import VenueBalanceOut, VenueBalancesOut
from app.utils.env_file import env_nonempty, env_value

logger = get_logger(__name__)

_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

# Stablecoins we can value 1:1 in USD without a price feed.
_STABLES = {"USDT", "USDC", "BUSD", "FDUSD", "TUSD", "DAI", "USD"}


def _sanitize_error(text: str) -> str:
    """Strip query strings (may contain signatures) from error text."""
    cleaned = text.strip()
    if "?" in cleaned:
        # Drop anything that looks like a signed URL query.
        parts = []
        for token in cleaned.split():
            if "signature=" in token.lower() or "timestamp=" in token.lower():
                parts.append(urlsplit(token)._replace(query="", fragment="").geturl().rstrip("?"))
            else:
                parts.append(token)
        cleaned = " ".join(parts)
    return cleaned[:300]


def _binance_error_message(resp: httpx.Response | None, fallback: str) -> str:
    """Prefer Binance JSON ``code``/``msg`` over raw httpx URL dumps."""
    if resp is not None:
        try:
            payload: Any = resp.json()
        except Exception:  # noqa: BLE001
            payload = None
        if isinstance(payload, dict):
            code = payload.get("code")
            msg = payload.get("msg") or payload.get("message")
            if code is not None and msg:
                return f"Binance {code}: {msg}"
            if msg:
                return str(msg)
        body = (resp.text or "").strip()
        if body:
            return _sanitize_error(f"HTTP {resp.status_code}: {body}")
        return f"HTTP {resp.status_code}"
    return _sanitize_error(fallback)


async def _binance_server_time_ms(client: httpx.AsyncClient, base_url: str) -> int:
    """Use exchange clock to avoid -1021 timestamp skew on signed calls."""
    try:
        resp = await client.get(f"{base_url}/api/v3/time")
        resp.raise_for_status()
        data = resp.json()
        server = int(data["serverTime"])
        return server
    except Exception:  # noqa: BLE001 - fall back to local clock
        return int(time.time() * 1000)


async def fetch_binance_account_balance(
    *,
    api_key: str,
    api_secret: str,
    base_url: str | None = None,
) -> VenueBalanceOut:
    """Signed Binance spot balances for the given credentials (user or platform)."""
    api_key = (api_key or "").strip()
    api_secret = (api_secret or "").strip()
    resolved_base = (base_url or env_value("BINANCE_BASE_URL") or "https://testnet.binance.vision").strip().rstrip("/")
    mode = "testnet" if "testnet" in resolved_base else ("demo" if "demo-api" in resolved_base else "live")

    if not api_key or not api_secret:
        return VenueBalanceOut(
            venue="binance",
            configured=False,
            mode="pending",
            detail="missing Binance API key/secret",
        )

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            timestamp = await _binance_server_time_ms(client, resolved_base)
            params = {
                "timestamp": timestamp,
                "recvWindow": 60000,
            }
            query = "&".join(f"{key}={value}" for key, value in params.items())
            signature = hmac.new(
                api_secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha256
            ).hexdigest()
            signed = dict(params)
            signed["signature"] = signature
            resp = await client.get(
                f"{resolved_base}/api/v3/account",
                params=signed,
                headers={"X-MBX-APIKEY": api_key},
            )
            if resp.status_code >= 400:
                err = _binance_error_message(resp, f"HTTP {resp.status_code}")
                logger.warning("Binance balance fetch failed", error=err)
                hint = ""
                if "-2015" in err:
                    hint = (
                        "; regenerate Spot Testnet key at testnet.binance.vision "
                        "(Enable Reading; IP whitelist or unrestricted)"
                    )
                return VenueBalanceOut(
                    venue="binance",
                    configured=True,
                    mode=mode,
                    detail=f"balance unavailable{hint}",
                    error=err,
                )
            data = resp.json()

        balances = data.get("balances", []) if isinstance(data, dict) else []
        free_usd = 0.0
        locked_usd = 0.0
        nonstable_assets = 0
        for bal in balances:
            asset = str(bal.get("asset", "")).upper()
            try:
                free = float(bal.get("free", 0) or 0)
                locked = float(bal.get("locked", 0) or 0)
            except (TypeError, ValueError):
                continue
            if asset in _STABLES:
                free_usd += free
                locked_usd += locked
            elif free + locked > 0:
                nonstable_assets += 1

        detail = f"Spot {mode}: stablecoin valuation"
        if nonstable_assets:
            detail += f"; {nonstable_assets} non-stable asset(s) held (not USD-valued)"
        return VenueBalanceOut(
            venue="binance",
            configured=True,
            mode=mode,
            refreshed=True,
            trading_usd=round(locked_usd, 2),
            balance_usd=round(free_usd, 2),
            total_usd=round(free_usd + locked_usd, 2),
            detail=detail,
        )
    except httpx.HTTPStatusError as exc:
        err = _binance_error_message(exc.response, str(exc))
        logger.warning("Binance balance fetch failed", error=err)
        return VenueBalanceOut(
            venue="binance",
            configured=True,
            mode=mode,
            detail="balance unavailable (see error)",
            error=err,
        )
    except Exception as exc:  # noqa: BLE001
        err = _sanitize_error(str(exc))
        logger.warning("Binance balance fetch failed", error=err)
        return VenueBalanceOut(
            venue="binance",
            configured=True,
            mode=mode,
            detail="balance unavailable (see error)",
            error=err,
        )


async def _binance_balance() -> VenueBalanceOut:
    """Ops/platform Binance account — never attach to a regular user's NavBar."""
    return await fetch_binance_account_balance(
        api_key=env_value("BINANCE_API_KEY") or "",
        api_secret=env_value("BINANCE_API_SECRET") or "",
        base_url=env_value("BINANCE_BASE_URL"),
    )


def _finam_balance() -> VenueBalanceOut:
    configured = env_nonempty("FINAM_API_KEY", "FINAM_TOKEN")
    account = env_nonempty("FINAM_ACCOUNT_ID")
    if not configured:
        return VenueBalanceOut(
            venue="finam",
            configured=False,
            mode="pending",
            detail="missing FINAM_API_KEY",
        )
    del account
    return VenueBalanceOut(
        venue="finam",
        configured=True,
        mode="market_data",
        detail="Ключ платформы — только данные; счета и сделки идут по ключам пользователей",
    )


def _tinkoff_balance() -> VenueBalanceOut:
    configured = env_nonempty("TINKOFF_API_TOKEN", "TINKOFF_TOKEN")
    if not configured:
        return VenueBalanceOut(
            venue="tinkoff",
            configured=False,
            mode="pending",
            detail="missing TINKOFF_API_TOKEN",
        )
    return VenueBalanceOut(
        venue="tinkoff",
        configured=True,
        mode="market_data",
        detail="Токен платформы — котировки и стакан Мосбиржи; счета и сделки идут по ключам пользователей",
    )


async def build_venue_balances() -> VenueBalancesOut:
    """Aggregate per-venue balances (Binance live; Finam/T-Bank platform keys are data-only)."""
    binance = await _binance_balance()
    finam = _finam_balance()
    tinkoff = _tinkoff_balance()

    venues = [binance, finam, tinkoff]
    total_trading = round(sum(v.trading_usd for v in venues), 2)
    total_balance = round(sum(v.balance_usd for v in venues), 2)
    total = round(sum(v.total_usd for v in venues), 2)

    return VenueBalancesOut(
        venues=venues,
        total_trading_usd=total_trading,
        total_balance_usd=total_balance,
        total_usd=total,
        as_of=datetime.now(timezone.utc).isoformat(),
    )
