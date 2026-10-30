"""Trading accounts settings API — Flow B user keys (Step 2-3, 5)."""
from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from app.core.config import settings
from app.core.deps import get_current_user_email, get_user_db
from app.schemas.trading_accounts import (
    ConnectRawKeyIn,
    ConnectResultOut,
    ConnectTokenIn,
    TokenizedFallbackOut,
    TradingAccountOut,
    TradingAccountsOverviewOut,
    VenueCardOut,
)
from app.services.portfolio.user_scope import get_user_by_email
from app.services.trading_keys.service import (
    connect_trading_account,
    list_trading_accounts,
    revoke_trading_account,
)
from app.services.trading_keys.validators import validate_venue_credentials
from app.utils.cache import cache_get
from app.utils.helpers import get_user_settings_key

router = APIRouter(prefix="/trading-accounts", tags=["trading-accounts"])

_VENUE_CARDS: list[dict[str, Any]] = [
    {
        "venue": "tokenized_equity",
        "title": "Tokenized US Equities",
        "description": "Connect Bybit API key for tokenized US equities (paper/testnet recommended).",
        "connection_type": "raw_key",
        "setup_url": "https://testnet.bybit.com/app/user/api-management",
        "setup_steps": [
            "Open Bybit → API Management (testnet for paper mode).",
            "Create a key with trade permissions only — disable withdrawals.",
            "Whitelist the platform server IP if required.",
            "Paste key + secret below and save.",
        ],
        "featured": True,
        "provider_options": ["bybit"],
    },
    {
        "venue": "binance",
        "title": "Binance",
        "description": "Для исполнения крипто-сделок в вашем счёте",
        "connection_type": "raw_key",
        "setup_url": "https://www.binance.com/en/my/settings/api-management",
        "setup_steps": [
            "Binance → Profile → API Management → Create API.",
            "Enable Spot trading; disable withdrawals and internal transfers.",
            "Restrict by IP if your account policy requires it.",
            "Paste API Key + Secret and validate.",
        ],
    },
    {
        "venue": "alpaca",
        "title": "Alpaca (US-акции)",
        "description": "OAuth для исполнения US-сделок — котировки доступны без вашего ключа",
        "connection_type": "oauth",
        "setup_url": "https://app.alpaca.markets/oauth/authorize",
        "setup_steps": [
            "Нажмите Connect via Alpaca — откроется OAuth Alpaca.",
            "Выберите paper или live account mode перед подключением.",
            "Подтвердите доступ; ключ вводить вручную не нужно.",
        ],
    },
    {
        "venue": "tinkoff",
        "title": "Т-Банк Инвестиции",
        "description": "Портфель, история операций и сделки на Мосбирже по вашему токену",
        "connection_type": "token",
        "setup_url": "https://www.tbank.ru/invest/settings/api/",
        "setup_steps": [
            "Т-Банк Инвестиции → Настройки → API → выпустить токен.",
            "Для просмотра портфеля достаточно токена «только чтение»; для сделок нужен полный доступ. Вывести деньги через API нельзя.",
            "Вставьте токен ниже и нажмите «Проверить и сохранить».",
            "«Боевой» — ваш реальный счёт, «Учебный» — песочница брокера с виртуальными деньгами.",
        ],
    },
    {
        "venue": "finam",
        "title": "Финам",
        "description": "Портфель, сделки и операции по счёту Финама через Trade API",
        "connection_type": "token",
        "setup_url": "https://api.finam.ru/docs/tokens",
        "setup_steps": [
            "Откройте страницу токенов Finam Trade API и выпустите токен (секрет).",
            "Для просмотра портфеля достаточно токена «только чтение», для сделок нужен токен с правом торговли.",
            "«Боевой» — реальный счёт, «Учебный» — демо-счёт Финама.",
            "Вставьте токен ниже и нажмите «Проверить и сохранить».",
        ],
    },
]


def _to_out(row: Any) -> TradingAccountOut:
    return TradingAccountOut(
        id=row.id,
        venue=row.venue,
        provider_type=getattr(row, "provider_type", None),
        account_mode=row.account_mode,
        status=row.status,
        label=row.label,
        account_display=row.account_display,
        permission_check_status=row.permission_check_status,
        withdraw_allowed=row.withdraw_allowed,
        permission_warning=row.permission_warning,
        last_health_at=getattr(row, "last_health_at", None),
        last_health_status=getattr(row, "last_health_status", None),
        rotation_due_at=row.rotation_due_at,
        connected=row.status == "active" and row.revoked_at is None,
    )


async def _require_user(db: AsyncSession, email: str):
    user = await get_user_by_email(db, email)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


async def _forbid_live_keys_without_grant(
    db: AsyncSession, user_id: str, account_mode: str, venue: str | None = None
) -> None:
    if str(account_mode).lower() != "live":
        return
    from app.services.trading_keys.service import VIEW_LIVE_VENUES

    if venue and venue.lower() in VIEW_LIVE_VENUES:
        return  # read-only use of a live broker token; orders are gated elsewhere
    from app.core.config import settings as app_settings
    from app.services.trading_keys.user_executor import user_has_full_trading_grant

    if not app_settings.live_trading_unlocked or not await user_has_full_trading_grant(db, user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Боевой счёт сейчас не подключается: на платформе работает только учебный режим. "
                "Выберите «Учебный»."
            ),
        )


async def _require_2fa_reauth(user: Any, reauth_token: str | None) -> None:
    """Admins must enroll 2FA; users with 2FA must present a fresh reauth_token."""
    from app.db.models import UserRole
    from app.domain.rbac import has_permission, map_legacy_user_role
    from app.services.two_factor import consume_reauth_token

    role = map_legacy_user_role(user.role.value if hasattr(user.role, "value") else str(user.role))
    is_admin = has_permission(role, "*") or (
        (user.role.value if hasattr(user.role, "value") else str(user.role)) == UserRole.ADMIN.value
    )
    enabled = bool(getattr(user, "two_factor_enabled", False))
    if is_admin and not enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Для администратора сначала включите 2FA в Настройках.",
        )
    if not enabled:
        return
    if not await consume_reauth_token(user.id, reauth_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Подтвердите действие кодом 2FA (reauth).",
        )


@router.get("", response_model=TradingAccountsOverviewOut)
async def list_accounts(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> TradingAccountsOverviewOut:
    user = await _require_user(db, email)
    rows = await list_trading_accounts(db, user.id)
    by_venue: dict[str, list[TradingAccountOut]] = {}
    for row in rows:
        by_venue.setdefault(row.venue, []).append(_to_out(row))

    venues = [
        VenueCardOut(
            venue=c["venue"],
            title=c["title"],
            description=c["description"],
            connection_type=c["connection_type"],
            setup_url=c.get("setup_url"),
            setup_steps=c.get("setup_steps", []),
            provider_options=c.get("provider_options", []),
            featured=bool(c.get("featured")),
            connected_accounts=by_venue.get(c["venue"], []),
        )
        for c in _VENUE_CARDS
    ]
    now = datetime.now(timezone.utc)
    rotation = [_to_out(r) for r in rows if r.rotation_due_at <= now and r.status == "active"]
    stored = await cache_get(get_user_settings_key(email)) or {}
    pref = "bybit"
    return TradingAccountsOverviewOut(
        venues=venues,
        rotation_reminders=rotation,
        tokenized_equity_provider=pref,
    )


@router.post("/connect", response_model=ConnectResultOut)
async def connect_raw_key(
    body: ConnectRawKeyIn,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> ConnectResultOut:
    user = await _require_user(db, email)
    await _forbid_live_keys_without_grant(db, user.id, body.account_mode)
    await _require_2fa_reauth(user, body.reauth_token)
    if body.provider_type == "mexc":
        return ConnectResultOut(ok=False, error="MEXC is deferred — Bybit only for now.")
    creds = {"api_key": body.api_key.strip(), "api_secret": body.api_secret.strip()}
    if body.base_url:
        from app.services.trading_keys.base_url_policy import BaseUrlRejected, checked_base_url

        try:
            creds["base_url"] = checked_base_url(body.base_url)
        except BaseUrlRejected as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    meta, validation = await connect_trading_account(
        db,
        user_id=user.id,
        venue=body.venue,
        credentials=creds,
        account_mode=body.account_mode,
        label=body.label,
        no_withdrawal_confirmed=body.no_withdrawal_confirmed,
        provider_type=body.provider_type,
    )
    if not validation.ok or meta is None:
        return ConnectResultOut(ok=False, error=validation.error)
    return ConnectResultOut(
        ok=True,
        account=_to_out(meta),
        account_display=validation.account_display,
    )


@router.post("/connect-token", response_model=ConnectResultOut)
async def connect_token(
    body: ConnectTokenIn,
    request: Request,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> ConnectResultOut:
    from app.services.legal import acceptance

    user = await _require_user(db, email)
    venue = "tinkoff" if body.venue == "tbank" else body.venue
    await _forbid_live_keys_without_grant(db, user.id, body.account_mode, venue)
    await _require_2fa_reauth(user, body.reauth_token)
    # L-06: data of the broker account is processed on a separate consent.
    if not body.consent_broker and not await acceptance.has_active(db, user.id, "consent_broker"):
        return ConnectResultOut(ok=False, error="Отметьте согласие на обработку данных брокерского счёта")
    if body.consent_broker and not await acceptance.has_active(db, user.id, "consent_broker"):
        await acceptance.record_acceptance(
            db,
            user.id,
            "consent_broker",
            ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    creds = {"token": body.token.strip()}
    meta, validation = await connect_trading_account(
        db,
        user_id=user.id,
        venue=venue,
        credentials=creds,
        account_mode=body.account_mode,
        label=body.label,
        no_withdrawal_confirmed=body.no_withdrawal_confirmed or venue in ("finam", "tinkoff"),
    )
    if not validation.ok or meta is None:
        return ConnectResultOut(ok=False, error=validation.error)
    return ConnectResultOut(ok=True, account=_to_out(meta), account_display=validation.account_display)


@router.post("/tinkoff/sync")
async def sync_tinkoff_account(
    account_mode: str = Query("live", pattern="^(paper|live)$"),
    full: bool = Query(False),
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> dict[str, Any]:
    """Load positions and operations from T-Bank into the user's book (no orders)."""
    from app.services.broker.tbank_api import TBankApiError
    from app.services.broker.tbank_sync import sync_user_tbank

    user = await _require_user(db, email)
    try:
        return await sync_user_tbank(db, user_id=user.id, account_mode=account_mode, full=full)
    except TBankApiError as exc:
        code = status.HTTP_409_CONFLICT if exc.kind == "busy" else status.HTTP_400_BAD_REQUEST
        if exc.kind == "not_found":
            code = status.HTTP_404_NOT_FOUND
        raise HTTPException(status_code=code, detail=exc.message) from exc


@router.post("/finam/sync")
async def sync_finam_account(
    account_mode: str = Query("live", pattern="^(paper|live)$"),
    full: bool = Query(False),
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> dict[str, Any]:
    """Load positions, trades and cash operations from Finam into the user's book."""
    from app.services.broker.finam_api import FinamApiError
    from app.services.broker.finam_sync import sync_user_finam

    user = await _require_user(db, email)
    try:
        return await sync_user_finam(db, user_id=user.id, account_mode=account_mode, full=full)
    except FinamApiError as exc:
        code = {"busy": status.HTTP_409_CONFLICT, "not_found": status.HTTP_404_NOT_FOUND}.get(
            exc.kind, status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=exc.message) from exc


@router.get("/finam/accounts")
async def finam_synced_accounts(
    account_mode: str = Query("live", pattern="^(paper|live)$"),
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> dict[str, Any]:
    from app.services.broker.finam_sync import book_mode_for
    from app.services.portfolio_book.store import get_book

    user = await _require_user(db, email)
    mode = book_mode_for(account_mode)
    accounts = [
        {"id": a.id, "status": a.status, "last_sync": a.last_sync.isoformat() if a.last_sync else None}
        for a in get_book().accounts_for(user_id=user.id)
        if a.venue == "finam" and a.mode == mode
    ]
    return {"accounts": accounts}


@router.get("/tinkoff/accounts")
async def tinkoff_synced_accounts(
    account_mode: str = Query("live", pattern="^(paper|live)$"),
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> dict[str, Any]:
    from app.services.broker.tbank_sync import book_mode_for, synced_accounts

    user = await _require_user(db, email)
    return {"accounts": synced_accounts(user.id, book_mode_for(account_mode))}


@router.delete("/{venue}", response_model=ConnectResultOut)
async def disconnect_account(
    venue: str,
    account_mode: str = Query("paper"),
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> ConnectResultOut:
    user = await _require_user(db, email)
    meta = await revoke_trading_account(
        db, user_id=user.id, venue=venue, account_mode=account_mode
    )
    if meta is None:
        raise HTTPException(status_code=404, detail="Account not connected")
    return ConnectResultOut(ok=True, account=_to_out(meta))


@router.post("/validate", response_model=ConnectResultOut)
async def validate_only(
    body: ConnectRawKeyIn,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> ConnectResultOut:
    user = await _require_user(db, email)
    await _forbid_live_keys_without_grant(db, user.id, body.account_mode)
    if body.provider_type == "mexc":
        return ConnectResultOut(ok=False, error="MEXC is deferred — Bybit only for now.")
    creds = {"api_key": body.api_key.strip(), "api_secret": body.api_secret.strip()}
    if body.base_url:
        from app.services.trading_keys.base_url_policy import BaseUrlRejected, checked_base_url

        try:
            creds["base_url"] = checked_base_url(body.base_url)
        except BaseUrlRejected as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    validation = await validate_venue_credentials(
        body.venue,
        creds,
        account_mode=body.account_mode,
        provider_type=body.provider_type,
    )
    if not validation.ok:
        return ConnectResultOut(ok=False, error=validation.error)
    return ConnectResultOut(ok=True, account_display=validation.account_display)


# ── Alpaca OAuth 2.0 (Step 2) ─────────────────────────────────────────────

_oauth_states: dict[str, dict[str, str]] = {}


@router.get("/alpaca/authorize")
async def alpaca_oauth_authorize(
    account_mode: str = Query("paper"),
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> RedirectResponse:
    user = await _require_user(db, email)
    await _forbid_live_keys_without_grant(db, user.id, account_mode)
    client_id = settings.ALPACA_OAUTH_CLIENT_ID.strip()
    redirect_uri = settings.ALPACA_OAUTH_REDIRECT_URI.strip()
    if not client_id or not redirect_uri:
        raise HTTPException(status_code=503, detail="Alpaca OAuth не настроен на сервере")

    state = secrets.token_urlsafe(24)
    _oauth_states[state] = {"user_id": user.id, "account_mode": account_mode, "email": email}
    params = urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "scope": "account:read trading",
        }
    )
    return RedirectResponse(f"https://app.alpaca.markets/oauth/authorize?{params}")


@router.get("/alpaca/callback")
async def alpaca_oauth_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_user_db),
) -> RedirectResponse:
    ctx = _oauth_states.pop(state, None)
    if ctx is None:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    token_url = "https://api.alpaca.markets/oauth/token"
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            token_url,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": settings.ALPACA_OAUTH_CLIENT_ID,
                "client_secret": settings.ALPACA_OAUTH_CLIENT_SECRET,
                "redirect_uri": settings.ALPACA_OAUTH_REDIRECT_URI,
            },
        )
        if resp.status_code >= 400:
            logger.warning(
                "oauth_token_exchange_failed status=%s body=%s",
                resp.status_code,
                (resp.text or "")[:500],
            )
            raise HTTPException(
                status_code=400,
                detail="Не удалось завершить подключение счёта. Попробуйте ещё раз.",
            )
        tokens = resp.json()

    access = tokens.get("access_token", "")
    # Alpaca OAuth returns trading keys in token response for partner apps
    api_key = tokens.get("api_key_id") or tokens.get("access_token", "")
    api_secret = tokens.get("api_secret") or access
    base = (
        "https://paper-api.alpaca.markets"
        if ctx.get("account_mode") == "paper"
        else "https://api.alpaca.markets"
    )
    await _forbid_live_keys_without_grant(db, ctx["user_id"], ctx.get("account_mode", "paper"))
    await connect_trading_account(
        db,
        user_id=ctx["user_id"],
        venue="alpaca",
        credentials={"api_key": api_key, "api_secret": api_secret, "base_url": base, "oauth": True},
        account_mode=ctx.get("account_mode", "paper"),
        label="Alpaca OAuth",
        no_withdrawal_confirmed=True,
    )
    frontend = settings.FRONTEND_BASE_URL.rstrip("/")
    return RedirectResponse(f"{frontend}/settings?alpaca=connected")


@router.get("/status")
async def trading_key_status(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> dict:
    """Lightweight status for Direct Deals no-key banner."""
    user = await _require_user(db, email)
    rows = await list_trading_accounts(db, user.id)
    active = [r for r in rows if r.status == "active" and r.revoked_at is None]
    return {
        "has_any_key": bool(active),
        "connected_venues": sorted({r.venue for r in active}),
        "settings_path": "/settings",
    }


@router.get("/tokenized/fallback-status", response_model=TokenizedFallbackOut)
async def tokenized_fallback_status(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_user_db),
) -> TokenizedFallbackOut:
    from app.services.trading_keys.tokenized_fallback import check_tokenized_fallback

    user = await _require_user(db, email)
    return await check_tokenized_fallback(db, user_id=user.id, email=email)
