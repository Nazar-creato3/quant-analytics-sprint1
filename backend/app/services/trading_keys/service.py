"""Trading key CRUD, connect, revoke, health-check."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.trading_keys import TradingKeyMetadataORM
from app.services.trading_keys.audit import log_trading_key_action
from app.services.trading_keys.store import save_credentials, vault_path_for
from app.services.trading_keys.validators import ValidationResult, validate_venue_credentials

ROTATION_DAYS = 90

# Brokers whose live token is useful without live trading: the portfolio is
# read from the broker. Orders still go through resolve_user_account_mode,
# which stays on paper until LIVE_TRADING_ENABLED and the user's grant allow it.
VIEW_LIVE_VENUES = frozenset({"tinkoff", "tbank", "finam"})


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def list_trading_accounts(db: AsyncSession, user_id: str) -> list[TradingKeyMetadataORM]:
    result = await db.execute(
        select(TradingKeyMetadataORM)
        .where(TradingKeyMetadataORM.user_id == user_id)
        .order_by(TradingKeyMetadataORM.venue, TradingKeyMetadataORM.account_mode)
    )
    return list(result.scalars().all())


async def connect_trading_account(
    db: AsyncSession,
    *,
    user_id: str,
    venue: str,
    credentials: dict[str, Any],
    account_mode: str = "paper",
    label: str | None = None,
    no_withdrawal_confirmed: bool = False,
    provider_type: str | None = None,
) -> tuple[TradingKeyMetadataORM | None, ValidationResult]:
    venue_norm = venue.lower()
    from app.services.execution.tokenized_provider_type import TOKENIZED_EQUITY_VENUE, TokenizedProvider

    if venue_norm in ("bybit", "mexc"):
        venue_norm = TOKENIZED_EQUITY_VENUE
    pt = TokenizedProvider.normalize(provider_type or venue).value if venue_norm == TOKENIZED_EQUITY_VENUE else None
    if pt == "mexc":
        return None, ValidationResult(
            ok=False,
            error="MEXC tokenized execution is deferred — Bybit only for now.",
        )
    if venue_norm == TOKENIZED_EQUITY_VENUE:
        pt = "bybit"
    if str(account_mode).lower() == "live" and venue_norm in {"binance", "bybit", "bitget", "mexc", TOKENIZED_EQUITY_VENUE}:
        from app.services.legal.gates import foreign_venues_live_allowed

        if not foreign_venues_live_allowed():
            return None, ValidationResult(
                ok=False,
                error="Подключение реального счёта на этой площадке сейчас недоступно. Доступен учебный (тестовый) счёт.",
            )
    if str(account_mode).lower() == "live" and venue_norm not in VIEW_LIVE_VENUES:
        from app.core.config import settings as app_settings
        from app.services.trading_keys.user_executor import user_has_full_trading_grant

        if not app_settings.live_trading_unlocked or not await user_has_full_trading_grant(
            db, user_id
        ):
            return None, ValidationResult(
                ok=False,
                error="Live API-ключи доступны после одобрения полного доступа в Admissions.",
            )

    if venue_norm in ("binance", "finam", "tinkoff", "tbank", TOKENIZED_EQUITY_VENUE) and not no_withdrawal_confirmed:
        return None, ValidationResult(
            ok=False,
            error="Подтвердите, что ключ создан без права на вывод средств",
        )

    credentials = {**credentials, **({"provider_type": pt} if pt else {})}
    if venue_norm == TOKENIZED_EQUITY_VENUE and account_mode == "paper" and not credentials.get("base_url"):
        credentials["base_url"] = "https://api-testnet.bybit.com"
    validation = await validate_venue_credentials(
        venue_norm, credentials, account_mode=account_mode, provider_type=pt
    )
    if not validation.ok:
        await log_trading_key_action(
            db,
            user_id=user_id,
            venue=venue_norm,
            action="connect_rejected",
            meta={"error": validation.error, "account_mode": account_mode},
        )
        await db.commit()
        return None, validation

    now = _now()
    key_id = str(uuid.uuid4())
    path = vault_path_for(user_id, venue_norm, account_mode)

    result = await db.execute(
        select(TradingKeyMetadataORM).where(
            TradingKeyMetadataORM.user_id == user_id,
            TradingKeyMetadataORM.venue == venue_norm,
            TradingKeyMetadataORM.account_mode == account_mode,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        key_id = existing.id
        existing.status = "active"
        existing.revoked_at = None
        existing.label = label or existing.label
        existing.vault_path = path
        existing.permission_check_status = validation.permission_check_status
        existing.withdraw_allowed = validation.withdraw_allowed
        existing.permission_warning = validation.permission_warning
        existing.provider_type = pt
        existing.account_display = validation.account_display
        existing.rotation_due_at = now + timedelta(days=ROTATION_DAYS)
        existing.updated_at = now
        meta = existing
    else:
        meta = TradingKeyMetadataORM(
            id=key_id,
            user_id=user_id,
            venue=venue_norm,
            account_mode=account_mode,
            label=label,
            vault_path=path,
            status="active",
            permission_check_status=validation.permission_check_status,
            withdraw_allowed=validation.withdraw_allowed,
            permission_warning=validation.permission_warning,
            provider_type=pt,
            account_display=validation.account_display,
            rotation_due_at=now + timedelta(days=ROTATION_DAYS),
            created_at=now,
            updated_at=now,
        )
        db.add(meta)

    await save_credentials(db, key_id=key_id, payload=credentials)
    await log_trading_key_action(
        db,
        user_id=user_id,
        key_id=key_id,
        venue=venue_norm,
        action="connected",
        meta={"account_mode": account_mode, "account_display": validation.account_display},
    )
    await db.commit()
    await db.refresh(meta)
    return meta, validation


async def revoke_trading_account(
    db: AsyncSession,
    *,
    user_id: str,
    venue: str,
    account_mode: str = "live",
) -> TradingKeyMetadataORM | None:
    result = await db.execute(
        select(TradingKeyMetadataORM).where(
            TradingKeyMetadataORM.user_id == user_id,
            TradingKeyMetadataORM.venue == venue.lower(),
            TradingKeyMetadataORM.account_mode == account_mode,
        )
    )
    meta = result.scalar_one_or_none()
    if meta is None:
        return None
    now = _now()
    meta.status = "revoked"
    meta.revoked_at = now
    meta.updated_at = now
    await log_trading_key_action(
        db,
        user_id=user_id,
        key_id=meta.id,
        venue=meta.venue,
        action="revoked",
    )
    await db.commit()
    return meta


async def health_check_key(db: AsyncSession, meta: TradingKeyMetadataORM) -> ValidationResult:
    from app.services.trading_keys.store import load_credentials

    creds = await load_credentials(db, meta.id, purpose="health_check", user_id=meta.user_id)
    if not creds:
        result = ValidationResult(ok=False, error="missing credentials")
    else:
        result = await validate_venue_credentials(meta.venue, creds, account_mode=meta.account_mode)

    now = _now()
    meta.last_health_at = now
    meta.last_health_status = "ok" if result.ok else "failed"
    meta.updated_at = now
    if not result.ok:
        meta.status = "unhealthy"
    elif meta.status == "unhealthy":
        meta.status = "active"

    await log_trading_key_action(
        db,
        user_id=meta.user_id,
        key_id=meta.id,
        venue=meta.venue,
        action="health_check",
        meta={"ok": result.ok, "error": result.error},
    )
    await db.commit()
    return result


async def keys_due_for_rotation(db: AsyncSession, user_id: str) -> list[TradingKeyMetadataORM]:
    now = _now()
    result = await db.execute(
        select(TradingKeyMetadataORM).where(
            TradingKeyMetadataORM.user_id == user_id,
            TradingKeyMetadataORM.status == "active",
            TradingKeyMetadataORM.rotation_due_at <= now,
        )
    )
    return list(result.scalars().all())


def excess_rights_alert(*, withdraw_allowed: bool | None, permission_warning: str | None) -> str | None:
    """Periodic re-check: extra withdraw rights must notify, never silently keep live."""
    if withdraw_allowed:
        return "ключ получил право вывода — отзовите и перевыпустите без withdraw"
    if permission_warning:
        return str(permission_warning)
    return None


async def recheck_permissions(db: AsyncSession, meta: TradingKeyMetadataORM) -> ValidationResult:
    result = await health_check_key(db, meta)
    alert = excess_rights_alert(
        withdraw_allowed=result.withdraw_allowed,
        permission_warning=result.permission_warning,
    )
    if alert:
        meta.permission_warning = alert
        await log_trading_key_action(
            db,
            user_id=meta.user_id,
            key_id=meta.id,
            venue=meta.venue,
            action="excess_rights",
            meta={"alert": alert},
        )
        await db.commit()
    return result
