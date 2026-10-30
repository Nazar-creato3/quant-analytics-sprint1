"""Parse EIA bulk JSON-lines exports and API v2 seriesid responses."""
from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from app.services.macro_registry.types import InternalObservation

EIA_BULK_ZIPS: dict[str, str] = {
    "PET": "PET.zip",
    "NG": "NG.zip",
}


def parse_eia_endpoint(endpoint: str) -> tuple[str, str] | None:
    """Return (mode, series_id) from registry endpoint."""
    if endpoint.startswith("adapter:eia_bulk:"):
        parts = endpoint.split(":", 2)
        if len(parts) == 3 and parts[2]:
            return ("bulk", parts[2])
    if endpoint.startswith("adapter:eia:"):
        parts = endpoint.split(":", 2)
        if len(parts) == 3 and parts[2]:
            return ("auto", parts[2])
    return None


def load_bulk_series(bulk_root: Path, series_id: str) -> str | None:
    """Load one EIA series JSON object from local bulk zips."""
    if not bulk_root.exists():
        return None

    prefix = series_id.split(".", 1)[0]
    zip_name = EIA_BULK_ZIPS.get(prefix)
    if zip_name is None:
        return None

    zip_paths: list[Path] = []
    if bulk_root.is_file() and bulk_root.suffix.lower() == ".zip":
        zip_paths.append(bulk_root)
    else:
        direct = bulk_root / zip_name
        if direct.is_file():
            zip_paths.append(direct)
        zip_paths.extend(sorted(bulk_root.glob("*.zip")))

    for zip_path in zip_paths:
        if zip_path.name.upper() != zip_name.upper() and zip_path != bulk_root:
            continue
        payload = _read_series_from_zip(zip_path, series_id)
        if payload:
            return payload
    return None


def _read_series_from_zip(zip_path: Path, series_id: str) -> str | None:
    with zipfile.ZipFile(zip_path, "r") as archive:
        txt_names = [n for n in archive.namelist() if n.lower().endswith(".txt")]
        if not txt_names:
            return None
        with archive.open(txt_names[0]) as handle:
            for raw_line in handle:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("series_id") == series_id:
                    return json.dumps(obj)
    return None


def parse_eia_series_payload(
    payload: str,
    *,
    instrument: str,
    series_id: str,
    unit: str,
    currency: str,
) -> list[InternalObservation]:
    """Normalize EIA bulk line or API v2 seriesid JSON into observations."""
    data = json.loads(payload)
    rows = _extract_data_rows(data)
    observations: list[InternalObservation] = []
    for date_raw, value_raw in rows:
        value = _parse_value(value_raw)
        if value is None:
            continue
        obs_time = _parse_eia_date(str(date_raw))
        if obs_time is None:
            continue
        period = obs_time.strftime("%Y-%m-%d")
        observations.append(
            InternalObservation(
                instrument=instrument,
                value=value,
                currency=currency,
                unit=unit,
                release_time=obs_time,
                observation_time=obs_time,
                period=period,
            )
        )
    observations.sort(key=lambda o: o.observation_time)
    return observations


def _extract_data_rows(data: dict) -> list[tuple[str | int | float, Any]]:
    if isinstance(data.get("data"), list):
        return [(row[0], row[1]) for row in data["data"] if isinstance(row, list) and len(row) >= 2]

    response = data.get("response")
    if isinstance(response, dict):
        response_data = response.get("data")
        if isinstance(response_data, list):
            extracted: list[tuple[str | int | float, Any]] = []
            for row in response_data:
                if isinstance(row, dict):
                    period = row.get("period") or row.get("date")
                    value = row.get("value")
                    if period is not None:
                        extracted.append((period, value))
                elif isinstance(row, list) and len(row) >= 2:
                    extracted.append((row[0], row[1]))
            return extracted
    return []


def _parse_value(value_raw: Any) -> float | None:
    if value_raw is None:
        return None
    if isinstance(value_raw, str):
        lowered = value_raw.strip().lower()
        if lowered in {"", "null", "w", "*", "na", "n/a"}:
            return None
    try:
        return float(value_raw)
    except (TypeError, ValueError):
        return None


def _parse_eia_date(date_raw: str) -> datetime | None:
    text = date_raw.strip()
    if not text:
        return None
    if len(text) == 8 and text.isdigit():
        return datetime.strptime(text, "%Y%m%d").replace(tzinfo=timezone.utc)
    if len(text) == 7 and text[4] == "Q":
        year = int(text[:4])
        quarter = int(text[5])
        month = quarter * 3
        return datetime(year, month, 28, tzinfo=timezone.utc)
    if len(text) == 6 and text.isdigit():
        return datetime.strptime(text, "%Y%m").replace(tzinfo=timezone.utc)
    if len(text) == 4 and text.isdigit():
        return datetime(int(text), 12, 31, tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None
