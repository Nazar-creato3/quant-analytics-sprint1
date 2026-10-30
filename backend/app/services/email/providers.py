"""Email provider abstraction with failover support."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class SendResult:
    provider: str
    message_id: str
    latency_ms: float


class EmailProviderError(Exception):
    def __init__(self, provider: str, message: str, *, retryable: bool = True):
        super().__init__(message)
        self.provider = provider
        self.retryable = retryable


class EmailProvider(Protocol):
    name: str

    async def send(
        self,
        *,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: str,
        idempotency_key: str,
    ) -> SendResult: ...


class StubEmailProvider:
    name = "stub"

    async def send(
        self,
        *,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: str,
        idempotency_key: str,
    ) -> SendResult:
        logger.info(
            "Email sent (stub)",
            to_email=to_email,
            subject=subject,
            idempotency_key=idempotency_key,
            preview=text_body[:120] if settings.is_development else "[redacted]",
        )
        return SendResult(provider=self.name, message_id=f"stub-{idempotency_key[:16]}", latency_ms=1.0)


class SendGridEmailProvider:
    name = "sendgrid"

    async def send(
        self,
        *,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: str,
        idempotency_key: str,
    ) -> SendResult:
        import time

        import httpx

        if not settings.SENDGRID_API_KEY:
            raise EmailProviderError(self.name, "SendGrid API key not configured", retryable=False)

        started = time.perf_counter()
        payload = {
            "personalizations": [{"to": [{"email": to_email}]}],
            "from": {"email": settings.EMAIL_FROM_ADDRESS, "name": settings.EMAIL_FROM_NAME},
            "subject": subject,
            "content": [
                {"type": "text/plain", "value": text_body},
                {"type": "text/html", "value": html_body},
            ],
        }
        headers = {
            "Authorization": f"Bearer {settings.SENDGRID_API_KEY}",
            "Content-Type": "application/json",
            "X-Idempotency-Key": idempotency_key,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post("https://api.sendgrid.com/v3/mail/send", json=payload, headers=headers)
        latency = (time.perf_counter() - started) * 1000
        if resp.status_code >= 500:
            raise EmailProviderError(self.name, f"SendGrid server error {resp.status_code}")
        if resp.status_code >= 400:
            raise EmailProviderError(
                self.name, f"SendGrid client error {resp.status_code}: {resp.text[:200]}", retryable=False
            )
        message_id = resp.headers.get("X-Message-Id", idempotency_key)
        return SendResult(provider=self.name, message_id=message_id, latency_ms=latency)


class PostmarkEmailProvider:
    name = "postmark"

    async def send(
        self,
        *,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: str,
        idempotency_key: str,
    ) -> SendResult:
        import time

        import httpx

        if not settings.POSTMARK_SERVER_TOKEN:
            raise EmailProviderError(self.name, "Postmark token not configured", retryable=False)

        started = time.perf_counter()
        payload = {
            "From": f"{settings.EMAIL_FROM_NAME} <{settings.EMAIL_FROM_ADDRESS}>",
            "To": to_email,
            "Subject": subject,
            "HtmlBody": html_body,
            "TextBody": text_body,
            "MessageStream": settings.POSTMARK_MESSAGE_STREAM or "outbound",
            "Headers": [{"Name": "X-Idempotency-Key", "Value": idempotency_key}],
        }
        headers = {"X-Postmark-Server-Token": settings.POSTMARK_SERVER_TOKEN}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post("https://api.postmarkapp.com/email", json=payload, headers=headers)
        latency = (time.perf_counter() - started) * 1000
        if resp.status_code >= 500:
            raise EmailProviderError(self.name, f"Postmark server error {resp.status_code}")
        if resp.status_code >= 400:
            raise EmailProviderError(
                self.name, f"Postmark client error {resp.status_code}: {resp.text[:200]}", retryable=False
            )
        data = resp.json()
        return SendResult(provider=self.name, message_id=str(data.get("MessageID", idempotency_key)), latency_ms=latency)


class UnisenderEmailProvider:
    name = "unisender"

    @staticmethod
    def _uses_classic_api() -> bool:
        url = settings.UNISENDER_API_URL.lower()
        if "api.unisender.com" in url:
            return True
        # Classic Unisender keys are ~40 char alnum; Go uses tapi_sk_*.
        key = settings.UNISENDER_API_KEY.strip()
        return bool(key) and not key.startswith("tapi_sk_")

    async def _send_classic(
        self,
        *,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: str,
        idempotency_key: str,
        started: float,
    ) -> SendResult:
        import time

        import httpx

        base = settings.UNISENDER_API_URL.rstrip("/")
        if not base.endswith("/api"):
            base = "https://api.unisender.com/ru/api"
        data = {
            "format": "json",
            "api_key": settings.UNISENDER_API_KEY,
            "email": to_email,
            "sender_name": settings.EMAIL_FROM_NAME,
            "sender_email": settings.EMAIL_FROM_ADDRESS,
            "subject": subject,
            "body": text_body or html_body,
            "list_id": "1",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{base}/sendEmail", data=data)
        latency = (time.perf_counter() - started) * 1000
        if resp.status_code >= 500:
            raise EmailProviderError(self.name, f"Unisender server error {resp.status_code}")
        payload = resp.json()
        if payload.get("error"):
            raise EmailProviderError(
                self.name,
                f"Unisender API error: {payload.get('error')}",
                retryable=False,
            )
        message_id = str(payload.get("result", {}).get("email_id", idempotency_key))
        return SendResult(provider=self.name, message_id=message_id, latency_ms=latency)

    async def send(
        self,
        *,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: str,
        idempotency_key: str,
    ) -> SendResult:
        import time

        import httpx

        if not settings.UNISENDER_API_KEY:
            raise EmailProviderError(self.name, "Unisender API key not configured", retryable=False)

        started = time.perf_counter()
        if self._uses_classic_api():
            return await self._send_classic(
                to_email=to_email,
                subject=subject,
                html_body=html_body,
                text_body=text_body,
                idempotency_key=idempotency_key,
                started=started,
            )

        base_url = settings.UNISENDER_API_URL.rstrip("/")
        payload = {
            "message": {
                "recipients": [{"email": to_email}],
                "subject": subject,
                "from_email": settings.EMAIL_FROM_ADDRESS,
                "from_name": settings.EMAIL_FROM_NAME,
                "body": {
                    "html": html_body,
                    "plaintext": text_body,
                },
                "headers": {"X-Idempotency-Key": idempotency_key},
            }
        }
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-API-KEY": settings.UNISENDER_API_KEY,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{base_url}/email/send.json", json=payload, headers=headers)
        latency = (time.perf_counter() - started) * 1000
        if resp.status_code >= 500:
            raise EmailProviderError(self.name, f"Unisender server error {resp.status_code}")
        if resp.status_code >= 400:
            raise EmailProviderError(
                self.name, f"Unisender client error {resp.status_code}: {resp.text[:200]}", retryable=False
            )
        data = resp.json()
        message_id = str(data.get("result", {}).get("email_id", idempotency_key))
        return SendResult(provider=self.name, message_id=message_id, latency_ms=latency)


class SesEmailProvider:
    name = "ses"

    async def send(
        self,
        *,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: str,
        idempotency_key: str,
    ) -> SendResult:
        import asyncio
        import time

        if not settings.AWS_SES_REGION or not settings.AWS_ACCESS_KEY_ID:
            raise EmailProviderError(self.name, "AWS SES not configured", retryable=False)

        started = time.perf_counter()

        def _send_sync() -> str:
            import boto3

            client = boto3.client(
                "ses",
                region_name=settings.AWS_SES_REGION,
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            )
            resp = client.send_email(
                Source=f"{settings.EMAIL_FROM_NAME} <{settings.EMAIL_FROM_ADDRESS}>",
                Destination={"ToAddresses": [to_email]},
                Message={
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {
                        "Text": {"Data": text_body, "Charset": "UTF-8"},
                        "Html": {"Data": html_body, "Charset": "UTF-8"},
                    },
                },
            )
            return resp["MessageId"]

        try:
            message_id = await asyncio.to_thread(_send_sync)
        except Exception as exc:
            raise EmailProviderError(self.name, str(exc)) from exc
        latency = (time.perf_counter() - started) * 1000
        return SendResult(provider=self.name, message_id=message_id, latency_ms=latency)


_PROVIDERS: dict[str, EmailProvider] = {
    "stub": StubEmailProvider(),
    "unisender": UnisenderEmailProvider(),
    "sendgrid": SendGridEmailProvider(),
    "postmark": PostmarkEmailProvider(),
    "ses": SesEmailProvider(),
}


def get_provider(name: str) -> EmailProvider:
    provider = _PROVIDERS.get(name.lower())
    if not provider:
        raise EmailProviderError(name, f"Unknown email provider: {name}", retryable=False)
    return provider


async def send_with_failover(
    *,
    to_email: str,
    subject: str,
    html_body: str,
    text_body: str,
    idempotency_key: str,
) -> SendResult:
    """Try primary provider, then secondary on failure."""
    primary = settings.EMAIL_PRIMARY_PROVIDER.lower()
    secondary = (settings.EMAIL_SECONDARY_PROVIDER or "").lower()
    chain = [primary]
    if secondary and secondary != primary:
        chain.append(secondary)

    last_error: EmailProviderError | None = None
    for provider_name in chain:
        provider = get_provider(provider_name)
        try:
            result = await provider.send(
                to_email=to_email,
                subject=subject,
                html_body=html_body,
                text_body=text_body,
                idempotency_key=idempotency_key,
            )
            logger.info(
                "Email dispatch success",
                provider=provider_name,
                to_email=to_email,
                message_id=result.message_id,
                latency_ms=round(result.latency_ms, 2),
                idempotency_key=idempotency_key,
            )
            return result
        except EmailProviderError as exc:
            last_error = exc
            logger.warning(
                "Email provider failed, trying failover",
                provider=provider_name,
                to_email=to_email,
                retryable=exc.retryable,
                error=str(exc),
            )
            if not exc.retryable:
                break
    raise last_error or EmailProviderError("unknown", "No email providers configured")
