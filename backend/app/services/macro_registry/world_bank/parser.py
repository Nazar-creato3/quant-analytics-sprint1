"""Parse World Bank API JSON and bulk CSV/xls/zip exports."""
from __future__ import annotations

import base64
import csv
import io
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.macro_registry.types import InternalObservation
from app.services.macro_registry.world_bank.xls_parser import parse_bulk_xls_bytes


def parse_world_bank_endpoint(endpoint: str) -> tuple[str, str, str] | None:
    """Return (mode, country_code, indicator_code) from registry endpoint."""
    if endpoint.startswith("adapter:world_bank:"):
        parts = endpoint.split(":")
        if len(parts) == 4:
            return ("api", parts[2], parts[3])
    if endpoint.startswith("adapter:world_bank_bulk:"):
        parts = endpoint.split(":")
        if len(parts) == 4:
            return ("bulk", parts[2], parts[3])
    return None


def parse_api_payload(
    payload: str,
    *,
    instrument: str,
    country_code: str,
    indicator_code: str,
    unit: str,
) -> list[InternalObservation]:
    """Parse World Bank v2 JSON response into internal observations."""
    data = json.loads(payload)
    if not isinstance(data, list) or len(data) < 2:
        return []
    rows = data[1]
    if not isinstance(rows, list):
        return []

    observations: list[InternalObservation] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        value_raw = row.get("value")
        date_raw = row.get("date")
        if value_raw is None or date_raw is None:
            continue
        try:
            value = float(value_raw)
        except (TypeError, ValueError):
            continue
        obs_time = _year_to_datetime(str(date_raw))
        observations.append(
            InternalObservation(
                instrument=instrument,
                value=value,
                currency=None,
                unit=unit,
                release_time=obs_time,
                observation_time=obs_time,
                period=str(date_raw),
            )
        )
    observations.sort(key=lambda o: o.observation_time)
    return observations


def parse_bulk_csv_text(
    csv_text: str,
    *,
    instrument: str,
    country_code: str,
    indicator_code: str,
    unit: str,
) -> list[InternalObservation]:
    """Parse a World Bank bulk CSV export for one country/indicator pair."""
    reader = csv.reader(io.StringIO(csv_text))
    rows = list(reader)
    header_idx = _find_header_row(rows)
    if header_idx is None:
        return []

    header = rows[header_idx]
    country_idx = _column_index(header, "Country Code")
    indicator_idx = _column_index(header, "Indicator Code")
    if country_idx is None:
        return []

    year_cols = [i for i, name in enumerate(header) if name.isdigit() and len(name) == 4]
    if not year_cols:
        return []
    year_start = min(year_cols)
    observations: list[InternalObservation] = []
    for row in rows[header_idx + 1 :]:
        if len(row) <= country_idx:
            continue
        if row[country_idx].strip().upper() != country_code.upper():
            continue
        if indicator_idx is not None and len(row) > indicator_idx:
            if row[indicator_idx].strip() != indicator_code:
                continue
        for col_idx in range(year_start, len(row)):
            if col_idx >= len(header):
                break
            year = header[col_idx].strip()
            if not year.isdigit() or len(year) != 4:
                continue
            cell = row[col_idx].strip()
            if not cell:
                continue
            try:
                value = float(cell)
            except ValueError:
                continue
            obs_time = _year_to_datetime(year)
            observations.append(
                InternalObservation(
                    instrument=instrument,
                    value=value,
                    currency=None,
                    unit=unit,
                    release_time=obs_time,
                    observation_time=obs_time,
                    period=year,
                )
            )
    observations.sort(key=lambda o: o.observation_time)
    return observations


def load_bulk_from_path(
    bulk_root: Path,
    *,
    country_code: str,
    indicator_code: str,
) -> tuple[str, str] | None:
    """Load bulk payload for indicator from directory or zip archive.

    Returns (payload, content_type) where content_type is text/csv or application/vnd.ms-excel.
    """
    if not bulk_root.exists():
        return None

    needle = indicator_code.replace(".", "_")
    if bulk_root.is_file() and bulk_root.suffix.lower() == ".zip":
        return _read_bulk_from_zip(bulk_root, country_code, indicator_code, needle)

    for path in bulk_root.rglob("*"):
        if path.suffix.lower() == ".zip":
            loaded = _read_bulk_from_zip(path, country_code, indicator_code, needle)
            if loaded:
                return loaded
        elif path.suffix.lower() == ".csv" and needle in path.name.upper():
            return (
                path.read_text(encoding="utf-8-sig", errors="replace"),
                "text/csv",
            )
        elif path.suffix.lower() == ".xls" and _matches_wb_xls(path.name, country_code, indicator_code):
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            return encoded, "application/vnd.ms-excel+b64"
    return None


def load_bulk_xls_bytes(
    bulk_root: Path,
    *,
    country_code: str,
    indicator_code: str,
) -> bytes | None:
    """Load raw .xls bytes for a country/indicator pair."""
    if not bulk_root.exists():
        return None

    if bulk_root.is_file() and bulk_root.suffix.lower() == ".zip":
        return _read_xls_bytes_from_zip(bulk_root, country_code, indicator_code)

    for path in bulk_root.rglob("*"):
        if path.suffix.lower() == ".zip":
            data = _read_xls_bytes_from_zip(path, country_code, indicator_code)
            if data:
                return data
        elif path.suffix.lower() == ".xls" and _matches_wb_xls(path.name, country_code, indicator_code):
            return path.read_bytes()
    return None


def _read_bulk_from_zip(
    zip_path: Path,
    country_code: str,
    indicator_code: str,
    needle: str,
) -> tuple[str, str] | None:
    xls_bytes = _read_xls_bytes_from_zip(zip_path, country_code, indicator_code)
    if xls_bytes is not None:
        encoded = base64.b64encode(xls_bytes).decode("ascii")
        return encoded, "application/vnd.ms-excel+b64"

    with zipfile.ZipFile(zip_path, "r") as archive:
        for name in archive.namelist():
            upper = name.upper()
            if not upper.endswith(".CSV"):
                continue
            if indicator_code.upper() not in upper and needle.upper() not in upper:
                continue
            with archive.open(name) as handle:
                return handle.read().decode("utf-8-sig", errors="replace"), "text/csv"
    return None


def _read_xls_bytes_from_zip(
    zip_path: Path,
    country_code: str,
    indicator_code: str,
) -> bytes | None:
    with zipfile.ZipFile(zip_path, "r") as archive:
        for name in archive.namelist():
            if not name.lower().endswith(".xls"):
                continue
            if _matches_wb_xls(name, country_code, indicator_code):
                with archive.open(name) as handle:
                    return handle.read()
    return None


def _matches_wb_xls(name: str, country_code: str, indicator_code: str) -> bool:
    upper = name.upper()
    pattern = rf"API_{re.escape(country_code.upper())}_{re.escape(indicator_code.upper())}_"
    return bool(re.search(pattern, upper))


def _find_header_row(rows: list[list[str]]) -> int | None:
    for idx, row in enumerate(rows):
        normalized = [cell.strip().strip('"') for cell in row]
        if "Country Code" in normalized:
            return idx
    return None


def _column_index(header: list[str], name: str) -> int | None:
    normalized = [cell.strip().strip('"') for cell in header]
    try:
        return normalized.index(name)
    except ValueError:
        return None


def _year_to_datetime(year: str) -> datetime:
    return datetime(int(year), 12, 31, tzinfo=timezone.utc)
