"""Bank of Canada Valet API helpers (public, no API key)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

BOC_VALET_BASE = "https://www.bankofcanada.ca/valet/observations"


def parse_boc_valet_observations(
    payload: dict[str, Any],
    *,
    series_id: str,
) -> list[dict[str, Any]]:
    """Parse BoC Valet observations JSON into normalized row dicts."""
    rows: list[dict[str, Any]] = []
    for obs in payload.get("observations", []):
        raw_date = obs.get("d")
        series_data = obs.get(series_id)
        if not raw_date or not isinstance(series_data, dict):
            continue
        raw_value = series_data.get("v")
        if raw_value in (None, "", "."):
            continue
        try:
            published_at = datetime.strptime(raw_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            value = float(raw_value)
        except (ValueError, TypeError):
            continue
        rows.append(
            {
                "value": value,
                "published_at": published_at,
            }
        )
    return rows
