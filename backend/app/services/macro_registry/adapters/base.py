"""IMacroAdapter interface and HTTP helpers (Prompt 42)."""
from __future__ import annotations

import asyncio
import hashlib
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

import httpx

from app.core.logging import get_logger
from app.services.macro_registry.types import InternalObservation, MacroSourceConfig, RawResponse

logger = get_logger(__name__)

MAX_RETRIES = 3
DEFAULT_TIMEOUT = 30.0


def compute_payload_hash(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class IMacroAdapter(ABC):
    """Common adapter interface for macro data sources."""

    def __init__(self, config: MacroSourceConfig) -> None:
        self.config = config

    @abstractmethod
    async def fetch(self, client: httpx.AsyncClient) -> RawResponse:
        """Fetch raw data from source."""

    @abstractmethod
    def normalize(self, raw: RawResponse) -> list[InternalObservation]:
        """Parse raw payload into internal observations."""

    async def fetch_with_retry(self, client: httpx.AsyncClient | None = None) -> RawResponse:
        """HTTP fetch with exponential backoff."""
        owns_client = client is None
        http = client or httpx.AsyncClient()
        delay = 1.0
        last_exc: Exception | None = None
        try:
            for attempt in range(MAX_RETRIES):
                try:
                    return await self.fetch(http)
                except Exception as exc:
                    last_exc = exc
                    logger.warning(
                        "macro_adapter_fetch_retry",
                        source_id=self.config.source_id,
                        attempt=attempt + 1,
                        error=str(exc),
                    )
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(delay)
                        delay *= 2.0
            raise last_exc or RuntimeError("fetch failed")
        finally:
            if owns_client:
                await http.aclose()


async def http_get_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    content: bytes | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> httpx.Response:
    delay = 1.0
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            if content is not None:
                response = await client.post(url, content=content, headers=headers, timeout=timeout)
            else:
                response = await client.get(url, headers=headers, params=params, timeout=timeout)
            response.raise_for_status()
            return response
        except Exception as exc:
            last_exc = exc
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(delay)
                delay *= 2.0
    raise last_exc or RuntimeError("HTTP request failed")


def build_raw_response(
    config: MacroSourceConfig,
    payload: str,
    *,
    content_type: str = "application/json",
    http_status: int = 200,
    fetched_at: datetime | None = None,
) -> RawResponse:
    ts = fetched_at or datetime.now(timezone.utc)
    return RawResponse(
        source_id=config.source_id,
        payload=payload,
        content_type=content_type,
        http_status=http_status,
        fetched_at=ts,
        payload_hash=compute_payload_hash(payload),
    )
