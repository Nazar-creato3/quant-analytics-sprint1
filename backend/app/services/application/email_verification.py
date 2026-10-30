"""Email magic-link verification for applications and account security."""
from __future__ import annotations

import asyncio
import hashlib
import secrets
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def generate_email_token(email: str) -> str:
    raw = secrets.token_urlsafe(32)
    digest = hashlib.sha256(f"{email}:{raw}:{settings.SECRET_KEY}".encode()).hexdigest()
    return f"{raw}.{digest[:16]}"


def build_verification_url(token: str) -> str:
    base = settings.EMAIL_VERIFICATION_BASE_URL.rstrip("/")
    return f"{base}/api/v1/applications/verify-email?token={token}"


def _smtp_configured() -> bool:
    return bool(settings.SMTP_HOST.strip() and settings.SMTP_USER.strip())


def _provider_configured() -> bool:
    if settings.UNISENDER_API_KEY.strip():
        return True
    provider = settings.EMAIL_PRIMARY_PROVIDER.lower()
    return provider not in ("", "stub")


def _send_smtp_sync(to_email: str, subject: str, body_text: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_USER
    msg["To"] = to_email
    msg.attach(MIMEText(body_text, "plain", "utf-8"))
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=30) as server:
        server.starttls()
        if settings.SMTP_PASSWORD:
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.sendmail(settings.SMTP_USER, [to_email], msg.as_string())


async def _send_via_provider(to_email: str, subject: str, body_text: str) -> None:
    from app.services.email.providers import get_provider, send_with_failover

    html_body = f"<pre style=\"font-family:sans-serif;white-space:pre-wrap\">{body_text}</pre>"
    idempotency_key = hashlib.sha256(f"{to_email}:{subject}:{body_text[:64]}".encode()).hexdigest()

    provider_name = settings.EMAIL_PROVIDER.lower()
    if provider_name == "unisender" or settings.UNISENDER_API_KEY.strip():
        provider = get_provider("unisender")
        await provider.send(
            to_email=to_email,
            subject=subject,
            html_body=html_body,
            text_body=body_text,
            idempotency_key=idempotency_key,
        )
        return

    await send_with_failover(
        to_email=to_email,
        subject=subject,
        html_body=html_body,
        text_body=body_text,
        idempotency_key=idempotency_key,
    )


async def _dispatch_email(to_email: str, subject: str, body_text: str) -> None:
    if _smtp_configured() and settings.EMAIL_PROVIDER.lower() in ("", "smtp"):
        await asyncio.to_thread(_send_smtp_sync, to_email, subject, body_text)
        logger.info("SMTP email dispatched", email=to_email, subject=subject)
        return
    if _provider_configured():
        await _send_via_provider(to_email, subject, body_text)
        logger.info("Provider email dispatched", email=to_email, subject=subject)
        return
    logger.info(
        "Email stub (no provider configured)",
        email=to_email,
        subject=subject,
        preview=body_text[:120] if settings.is_development else "[redacted]",
    )


async def send_verification_email(email: str, token: str) -> None:
    url = build_verification_url(token)
    body = (
        "Подтвердите email, перейдя по ссылке:\n\n"
        f"{url}\n\n"
        "Ссылка действует 24 часа."
    )
    await _dispatch_email(email, "Apex Intel — подтверждение email", body)


def build_password_change_url(token: str) -> str:
    base = settings.EMAIL_VERIFICATION_BASE_URL.rstrip("/")
    return f"{base}/account?password_token={token}"


async def send_password_change_email(
    email: str,
    *,
    code: str,
    magic_token: str,
) -> None:
    """Send OTP and optional magic link for password change confirmation."""
    link = build_password_change_url(magic_token)
    body = (
        "Запрос на смену пароля в Apex Intel.\n\n"
        f"Код подтверждения: {code}\n"
        f"Действителен 15 минут.\n\n"
        f"Или перейдите по ссылке:\n{link}\n\n"
        "Если вы не запрашивали смену пароля, проигнорируйте это письмо."
    )
    if _smtp_configured() or _provider_configured():
        await _dispatch_email(email, "Apex Intel — подтверждение смены пароля", body)
        logger.info("Password change email dispatched", email=email)
    else:
        logger.info(
            "Password change email (stub)",
            email=email,
            code=code if settings.is_development else "[redacted]",
            link=link if settings.is_development else "[redacted]",
        )


async def send_credentials_email(email: str, plaintext_password: str) -> None:
    """One-time credential delivery — password must never appear in production logs."""
    body = (
        "Вам выдан доступ к Quant Analytics.\n\n"
        f"Логин: {email}\n"
        f"Временный пароль: {plaintext_password}\n\n"
        "При первом входе система попросит сменить пароль."
    )
    await _dispatch_email(email, "Quant Analytics — доступ", body)
    logger.info("Credential email dispatched", email=email)
