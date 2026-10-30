"""Parse World Bank bulk .xls exports (API downloadformat=excel)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.services.macro_registry.types import InternalObservation


def _xlrd():
    try:
        import xlrd
    except ImportError as exc:
        raise RuntimeError("нет данных") from exc
    return xlrd


def parse_bulk_xls_bytes(
    xls_bytes: bytes,
    *,
    instrument: str,
    country_code: str,
    indicator_code: str,
    unit: str,
) -> list[InternalObservation]:
    """Parse a World Bank per-country indicator .xls workbook."""
    workbook = _xlrd().open_workbook(file_contents=xls_bytes)
    sheet = workbook.sheet_by_name("Data") if "Data" in workbook.sheet_names() else workbook.sheet_by_index(0)
    header_idx = _find_header_row(sheet)
    if header_idx is None:
        return []

    header = [_cell_str(sheet.cell_value(header_idx, col)) for col in range(sheet.ncols)]
    country_idx = _column_index(header, "Country Code")
    indicator_idx = _column_index(header, "Indicator Code")
    if country_idx is None:
        return []

    year_cols = [
        col
        for col, name in enumerate(header)
        if name.isdigit() and len(name) == 4
    ]
    if not year_cols:
        return []

    observations: list[InternalObservation] = []
    for row_idx in range(header_idx + 1, sheet.nrows):
        row_country = _cell_str(sheet.cell_value(row_idx, country_idx))
        if row_country.upper() != country_code.upper():
            continue
        if indicator_idx is not None:
            row_indicator = _cell_str(sheet.cell_value(row_idx, indicator_idx))
            if row_indicator and row_indicator != indicator_code:
                continue
        for col_idx in year_cols:
            year = header[col_idx]
            value = _cell_float(sheet.cell_value(row_idx, col_idx))
            if value is None:
                continue
            obs_time = datetime(int(year), 12, 31, tzinfo=timezone.utc)
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


def _find_header_row(sheet: Any) -> int | None:
    for row_idx in range(min(sheet.nrows, 20)):
        values = [_cell_str(sheet.cell_value(row_idx, col)) for col in range(sheet.ncols)]
        if "Country Code" in values:
            return row_idx
    return None


def _column_index(header: list[str], name: str) -> int | None:
    try:
        return header.index(name)
    except ValueError:
        return None


def _cell_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _cell_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
