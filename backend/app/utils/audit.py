"""
Audit logging service.
Writes structured, tamper-evident audit records for every significant action.

Usage:
    from app.utils.audit import audit
    await audit.log(db, action="maneuver_approve", user_id=..., resource_id=..., details={...})
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger

logger = get_logger(__name__)

# Actions catalogue — keep this list exhaustive and consistent.
class AuditAction:
    # Auth
    LOGIN_SUCCESS        = "login_success"
    LOGIN_FAILED         = "login_failed"
    LOGOUT               = "logout"
    TOKEN_REFRESH        = "token_refresh"
    REGISTER             = "register"
    WHITELIST_ADD        = "whitelist_add"
    WHITELIST_REMOVE     = "whitelist_remove"

    # Pipeline
    PIPELINE_TRIGGERED   = "pipeline_triggered"
    PIPELINE_COMPLETE    = "pipeline_complete"
    PIPELINE_FAILED      = "pipeline_failed"

    # Maneuvers
    MANEUVER_APPROVE     = "maneuver_approve"
    MANEUVER_REJECT      = "maneuver_reject"
    MANEUVER_EDIT        = "maneuver_edit"
    MANEUVER_EXECUTED    = "maneuver_executed"
    MANEUVER_CANCELLED   = "maneuver_cancelled"
    MANEUVER_INVALIDATED = "maneuver_invalidated"

    # DealIntent
    DEAL_INTENT_APPROVE  = "deal_intent_approve"
    DEAL_INTENT_REJECT   = "deal_intent_reject"
    DEAL_INTENT_EDIT     = "deal_intent_edit"
    DEAL_INTENT_CANCEL   = "deal_intent_cancel"

    # Execution
    ORDER_SUBMITTED      = "order_submitted"
    ORDER_FILLED         = "order_filled"
    ORDER_REJECTED       = "order_rejected"
    ORDER_CANCELLED      = "order_cancelled"

    # Backtesting
    BACKTEST_STARTED     = "backtest_started"
    BACKTEST_COMPLETE    = "backtest_complete"
    BACKTEST_FAILED      = "backtest_failed"

    # Data ingestion
    DATA_INGESTION_RUN   = "data_ingestion_run"
    NEWS_INGESTION_RUN   = "news_ingestion_run"

    # System
    SETTINGS_CHANGED     = "settings_changed"
    WATCHLIST_UPDATED    = "watchlist_updated"
    LIVE_TRADING_ENABLED = "live_trading_enabled"

    # Origination / admissions / security
    ADMISSION_CREATE = "admission_create"
    ROLE_ASSIGNED = "role_assigned"
    ROLE_REVOKED = "role_revoked"
    PERMISSION_CHANGED = "permission_changed"
    DEVICE_REGISTERED = "device_registered"
    DEVICE_REVOKED = "device_revoked"
    DEVICE_OVERRIDE = "device_override"
    TRIAL_DENIED_DUPLICATE = "trial_denied_duplicate"
    ACCOUNT_CLUSTER_MERGED = "account_cluster_merged"
    BREAK_GLASS_TRIGGERED = "break_glass_triggered"
    MFA_DISABLED = "mfa_disabled"
    ADMIN_MFA_VERIFIED = "admin_mfa_verified"
    FLEET_AUDIT_VIEW = "fleet_audit_view"

    # CRM sync (Twenty)
    CRM_SYNC_SUCCESS = "crm_sync_success"
    CRM_SYNC_FAILED = "crm_sync_failed"
    CRM_SYNC_SKIPPED = "crm_sync_skipped"

    CHAT_GROUNDING = "chat_grounding"

    # Personal data access (152-FZ art. 19: journal of actions with PD;
    # the basis for the 24/72-hour leak report under art. 21 part 3.1)
    PD_EXPORT = "pd_export"
    PD_DELETE_REQUEST = "pd_delete_request"
    CONSENT_GIVEN = "consent_given"
    CONSENT_REVOKED = "consent_revoked"


class AuditLogger:
    """
    Async audit trail writer.
    All writes are fire-and-forget with local fallback to structlog.
    """

    async def log(
        self,
        db: AsyncSession,
        *,
        action: str,
        user_id: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        details: dict[str, Any] | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        success: bool = True,
        error: str | None = None,
    ) -> None:
        """
        Write an audit record to the database.
        Falls back to structured log on DB failure.
        """
        from app.db.models import AuditLog

        record = AuditLog(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details or {},
            ip_address=ip_address,
            user_agent=user_agent,
            success=success,
            error=error,
            timestamp=datetime.now(timezone.utc),
        )

        try:
            db.add(record)
            await db.commit()
        except Exception as exc:
            # Reset the session so callers can still refresh/commit after audit failure.
            try:
                await db.rollback()
            except Exception as rollback_exc:
                logger.warning("Audit rollback failed", error=str(rollback_exc))
            logger.error(
                "Audit DB write failed — falling back to log",
                action=action,
                user_id=user_id,
                error=str(exc),
            )
            # Structured fallback so nothing is silently lost
            logger.info(
                "AUDIT_FALLBACK",
                action=action,
                user_id=user_id,
                resource_type=resource_type,
                resource_id=resource_id,
                details=details,
                success=success,
                error=error,
            )

    async def log_fire_forget(
        self,
        db: AsyncSession,
        **kwargs: Any,
    ) -> None:
        """
        Non-blocking audit log write.
        Schedules the write as a background task so it never blocks the caller.
        """
        import asyncio
        asyncio.create_task(self.log(db, **kwargs))  # noqa: RUF006


# Singleton
audit = AuditLogger()
