"""Server-side product events. Does not take an email or a token."""
from __future__ import annotations

from typing import Any

from app.services.product_analytics.service import record_event


def emit_server_event(
    name: str,
    subject: str,
    properties: dict[str, Any] | None = None,
) -> dict[str, str]:
    return record_event(
        name=name,
        side="server",
        subject=subject,
        properties=properties or {},
        consent=True,
        do_not_track=False,
    )
