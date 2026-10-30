"""Parse Eurostat SDMX-CSV bulk exports into macro observations."""
from __future__ import annotations

import csv
import hashlib
import io
import re
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, TextIO

from app.services.macro_registry.eurostat.bulk import DatasetLocation, build_dataset_index
from app.services.macro_registry.eurostat.indicators import (
    EUROSTAT_INDICATORS,
    EurostatIndicatorSpec,
    spec_by_id,
)
from app.services.macro_registry.types import InternalObservation

_QUARTER_RE = re.compile(r"^(\d{4})-Q([1-4])$")

# Datasets too large to load into memory during macro refresh (e.g. ~690MB namq_10_gdp.csv).
_STREAMING_DATASET_FILES = frozenset({"namq_10_gdp.csv"})
_STREAMING_SIZE_THRESHOLD_BYTES = 32 * 1024 * 1024
STREAM_PAYLOAD_PREFIX = "eurostat-stream:v1:"


def parse_eurostat_endpoint(endpoint: str) -> str | None:
    if endpoint.startswith("adapter:eurostat_bulk:"):
        parts = endpoint.split(":", 2)
        if len(parts) == 3 and parts[2]:
            return parts[2]
    return None


def parse_sdmx_csv_bytes(
    payload: bytes,
    *,
    spec: EurostatIndicatorSpec,
) -> list[InternalObservation]:
    text = payload.decode("utf-8-sig", errors="replace")
    return parse_sdmx_csv_text(text, spec=spec)


def parse_sdmx_csv_text(
    csv_text: str,
    *,
    spec: EurostatIndicatorSpec,
) -> list[InternalObservation]:
    return parse_sdmx_csv_stream(io.StringIO(csv_text), spec=spec)


def parse_sdmx_csv_stream(
    text_stream: TextIO,
    *,
    spec: EurostatIndicatorSpec,
) -> list[InternalObservation]:
    reader = csv.DictReader(text_stream)
    if reader.fieldnames is None:
        return []

    if spec.derive == "yoy_quarterly":
        return _derive_yoy_quarterly(reader, spec=spec)

    observations: list[InternalObservation] = []
    for row in reader:
        if not _row_matches(row, spec):
            continue
        value = _parse_value(row.get("OBS_VALUE"))
        if value is None:
            continue
        period = (row.get("TIME_PERIOD") or "").strip()
        obs_time = _period_to_datetime(period, row.get("freq"))
        if obs_time is None:
            continue
        observations.append(
            InternalObservation(
                instrument=spec.symbol,
                value=value,
                currency=None,
                unit=spec.unit,
                release_time=obs_time,
                observation_time=obs_time,
                period=period,
            )
        )
    observations.sort(key=lambda o: o.observation_time)
    return observations


def should_stream_spec_csv(
    *,
    store_dir: Path,
    roots: Iterable[Path],
    spec: EurostatIndicatorSpec,
) -> bool:
    if spec.dataset_file.lower() in _STREAMING_DATASET_FILES:
        return True
    direct = store_dir / spec.dataset_file
    if direct.is_file():
        try:
            return direct.stat().st_size >= _STREAMING_SIZE_THRESHOLD_BYTES
        except OSError:
            return False
    return spec.dataset_file.lower() in _STREAMING_DATASET_FILES


def csv_source_fingerprint(
    *,
    store_dir: Path,
    roots: Iterable[Path],
    spec: EurostatIndicatorSpec,
) -> str:
    """Stable hash for raw-response dedup without reading the full CSV."""
    digest = hashlib.sha256()
    digest.update(spec.dataset_file.lower().encode())
    direct = store_dir / spec.dataset_file
    if direct.is_file():
        stat = direct.stat()
        digest.update(b"file")
        digest.update(str(stat.st_size).encode())
        digest.update(str(int(stat.st_mtime)).encode())
        return digest.hexdigest()[:32]

    index = build_dataset_index(roots)
    loc: DatasetLocation | None = index.get(spec.dataset_file.lower())
    if loc is None:
        raise FileNotFoundError(f"Missing Eurostat dataset {spec.dataset_file}")
    zip_stat = loc.zip_path.stat()
    digest.update(b"zip")
    digest.update(str(loc.zip_path).encode())
    digest.update(str(zip_stat.st_size).encode())
    digest.update(str(int(zip_stat.st_mtime)).encode())
    digest.update(loc.member_name.encode())
    return digest.hexdigest()[:32]


def build_stream_payload_marker(*, spec_id: str, fingerprint: str) -> str:
    return f"{STREAM_PAYLOAD_PREFIX}{spec_id}:{fingerprint}"


def parse_stream_payload_marker(payload: str) -> str | None:
    if not payload.startswith(STREAM_PAYLOAD_PREFIX):
        return None
    rest = payload[len(STREAM_PAYLOAD_PREFIX) :]
    spec_id, _, _fp = rest.partition(":")
    return spec_id or None


@contextmanager
def open_spec_csv_text(
    *,
    store_dir: Path,
    roots: Iterable[Path],
    spec: EurostatIndicatorSpec,
) -> Iterator[TextIO]:
    """Open SDMX-CSV as a text stream (file or zip member) without loading entirely into RAM."""
    direct = store_dir / spec.dataset_file
    if direct.is_file():
        with direct.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            yield handle
        return

    index = build_dataset_index(roots)
    loc: DatasetLocation | None = index.get(spec.dataset_file.lower())
    if loc is None:
        raise FileNotFoundError(f"Missing Eurostat dataset {spec.dataset_file}")

    with zipfile.ZipFile(loc.zip_path, "r") as archive:
        with archive.open(loc.member_name, "r") as binary:
            text_wrapper = io.TextIOWrapper(
                binary,
                encoding="utf-8-sig",
                errors="replace",
                newline="",
            )
            try:
                yield text_wrapper
            finally:
                text_wrapper.detach()


def load_spec_csv(
    *,
    store_dir: Path,
    roots: Iterable[Path],
    spec: EurostatIndicatorSpec,
) -> bytes | None:
    direct = store_dir / spec.dataset_file
    if direct.is_file():
        return direct.read_bytes()

    index = build_dataset_index(roots)
    loc: DatasetLocation | None = index.get(spec.dataset_file.lower())
    if loc is None:
        return None
    with zipfile.ZipFile(loc.zip_path, "r") as archive:
        return archive.read(loc.member_name)


def observations_for_spec(
    *,
    store_dir: Path,
    roots: Iterable[Path],
    spec_id: str,
) -> list[InternalObservation]:
    spec = spec_by_id(spec_id)
    if spec is None:
        return []
    if should_stream_spec_csv(store_dir=store_dir, roots=roots, spec=spec):
        with open_spec_csv_text(store_dir=store_dir, roots=roots, spec=spec) as stream:
            return parse_sdmx_csv_stream(stream, spec=spec)
    payload = load_spec_csv(store_dir=store_dir, roots=roots, spec=spec)
    if payload is None:
        return []
    return parse_sdmx_csv_bytes(payload, spec=spec)


def available_spec_ids(roots: Iterable[Path]) -> frozenset[str]:
    index = build_dataset_index(roots)
    available: set[str] = set()
    for spec in EUROSTAT_INDICATORS:
        if spec.dataset_file.lower() in index:
            available.add(spec.source_id)
    return frozenset(available)


def _derive_yoy_quarterly(
    reader: csv.DictReader,
    *,
    spec: EurostatIndicatorSpec,
) -> list[InternalObservation]:
    levels: dict[str, float] = {}
    for row in reader:
        if not _row_matches(row, spec):
            continue
        value = _parse_value(row.get("OBS_VALUE"))
        if value is None:
            continue
        period = (row.get("TIME_PERIOD") or "").strip()
        levels[period] = value

    if not levels:
        return []

    latest_period = max(levels.keys(), key=_period_sort_key)
    prior_period = _prior_year_quarter(latest_period)
    if prior_period is None or prior_period not in levels:
        return []

    prior_val = levels[prior_period]
    if prior_val <= 0:
        return []

    yoy = (levels[latest_period] / prior_val - 1.0) * 100.0
    obs_time = _period_to_datetime(latest_period, "Q")
    if obs_time is None:
        return []

    return [
        InternalObservation(
            instrument=spec.symbol,
            value=round(yoy, 4),
            currency=None,
            unit=spec.unit,
            release_time=obs_time,
            observation_time=obs_time,
            period=latest_period,
        )
    ]


def _row_matches(row: dict[str, str | None], spec: EurostatIndicatorSpec) -> bool:
    geo = (row.get("geo") or "").strip()
    if geo != spec.geo:
        return False
    for key, expected in spec.filters.items():
        actual = (row.get(key) or "").strip()
        if actual != expected:
            return False
    return True


def _parse_value(raw: str | None) -> float | None:
    if raw is None:
        return None
    cell = raw.strip()
    if not cell or cell in {":", ":", "NaN"}:
        return None
    try:
        return float(cell)
    except ValueError:
        return None


def _period_sort_key(period: str) -> tuple[int, int]:
    match = _QUARTER_RE.match(period)
    if match:
        return (int(match.group(1)), int(match.group(2)))
    if period.isdigit() and len(period) == 4:
        return (int(period), 0)
    if len(period) >= 7 and period[4] == "-":
        try:
            return (int(period[:4]), int(period[5:7]))
        except ValueError:
            pass
    return (0, 0)


def _prior_year_quarter(period: str) -> str | None:
    match = _QUARTER_RE.match(period)
    if not match:
        return None
    year = int(match.group(1)) - 1
    quarter = match.group(2)
    return f"{year}-Q{quarter}"


def _period_to_datetime(period: str, freq: str | None) -> datetime | None:
    freq_norm = (freq or "").strip().upper()
    match = _QUARTER_RE.match(period)
    if match or freq_norm == "Q":
        q_match = _QUARTER_RE.match(period)
        if not q_match:
            return None
        year = int(q_match.group(1))
        quarter = int(q_match.group(2))
        month = {1: 3, 2: 6, 3: 9, 4: 12}[quarter]
        return datetime(year, month, 1, tzinfo=timezone.utc)

    if period.isdigit() and len(period) == 4:
        return datetime(int(period), 12, 31, tzinfo=timezone.utc)

    if len(period) >= 7 and period[4] == "-":
        try:
            year = int(period[:4])
            month = int(period[5:7])
            return datetime(year, month, 1, tzinfo=timezone.utc)
        except ValueError:
            return None
    return None
