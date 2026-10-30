"""Locate Eurostat bulk zips and extract SDMX-CSV slices into backend/data/eurostat."""
from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from app.services.macro_registry.eurostat.indicators import EUROSTAT_INDICATORS, EurostatIndicatorSpec

MANIFEST_NAME = "manifest.json"


@dataclass(frozen=True, slots=True)
class DatasetLocation:
    dataset_file: str
    zip_path: Path
    member_name: str


def discover_data_roots(configured: str | None, repo_root: Path) -> list[Path]:
    """Return search roots for ESTAT zip archives (newest paths first)."""
    roots: list[Path] = []
    if configured and configured.strip():
        path = Path(configured.strip())
        if path.is_dir():
            roots.append(path)

    market_dir = repo_root / "рыночные данные"
    euro_sub = market_dir / "ЕВРОСТАТ"
    if euro_sub.is_dir():
        roots.append(euro_sub)
    if market_dir.is_dir():
        roots.append(market_dir)

    deduped: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root.resolve()).lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(root)
    return deduped


def iter_estat_zip_paths(roots: Iterable[Path]) -> list[Path]:
    zips: list[Path] = []
    for root in roots:
        if root.is_file() and root.suffix.lower() == ".zip":
            zips.append(root)
            continue
        if not root.is_dir():
            continue
        for path in sorted(root.glob("**/*.zip")):
            name = path.name.upper()
            if "ESTAT" in name or name.startswith("ESTAT_DOWNLOADS"):
                zips.append(path)
    return zips


def build_dataset_index(roots: Iterable[Path]) -> dict[str, DatasetLocation]:
    """Map dataset basename (lower) -> newest zip containing that member."""
    index: dict[str, DatasetLocation] = {}
    zip_paths = iter_estat_zip_paths(roots)
    for zip_path in zip_paths:
        try:
            with zipfile.ZipFile(zip_path, "r") as archive:
                for member in archive.namelist():
                    base = Path(member).name
                    if not base.lower().endswith(".csv"):
                        continue
                    key = base.lower()
                    prev = index.get(key)
                    if prev is None or zip_path.stat().st_mtime >= prev.zip_path.stat().st_mtime:
                        index[key] = DatasetLocation(
                            dataset_file=base,
                            zip_path=zip_path,
                            member_name=member,
                        )
        except (zipfile.BadZipFile, OSError):
            continue
    return index


def _file_fingerprint(path: Path) -> str:
    stat = path.stat()
    digest = hashlib.sha256()
    digest.update(str(stat.st_size).encode())
    digest.update(str(int(stat.st_mtime)).encode())
    return digest.hexdigest()[:16]


def load_manifest(store_dir: Path) -> dict:
    path = store_dir / MANIFEST_NAME
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_manifest(store_dir: Path, manifest: dict) -> None:
    store_dir.mkdir(parents=True, exist_ok=True)
    manifest.setdefault("updated_at", datetime.now(timezone.utc).isoformat())
    (store_dir / MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def extract_datasets(
    store_dir: Path,
    roots: Iterable[Path],
    specs: Iterable[EurostatIndicatorSpec] | None = None,
    *,
    force: bool = False,
) -> dict[str, str]:
    """Extract required CSV members into store_dir. Returns status per source_id."""
    store_dir.mkdir(parents=True, exist_ok=True)
    index = build_dataset_index(roots)
    manifest = load_manifest(store_dir)
    datasets_meta: dict = manifest.setdefault("datasets", {})
    results: dict[str, str] = {}

    for spec in specs or EUROSTAT_INDICATORS:
        key = spec.dataset_file.lower()
        loc = index.get(key)
        if loc is None:
            if spec.optional:
                results[spec.source_id] = "skipped_optional_missing"
            else:
                results[spec.source_id] = f"missing_dataset:{spec.dataset_file}"
            continue

        zip_fp = _file_fingerprint(loc.zip_path)
        prior = datasets_meta.get(spec.source_id) or {}
        if (
            not force
            and prior.get("zip_fingerprint") == zip_fp
            and prior.get("dataset_file") == spec.dataset_file
            and (store_dir / spec.dataset_file).is_file()
        ):
            results[spec.source_id] = "unchanged"
            continue

        target = store_dir / spec.dataset_file
        with zipfile.ZipFile(loc.zip_path, "r") as archive:
            target.write_bytes(archive.read(loc.member_name))

        datasets_meta[spec.source_id] = {
            "dataset_file": spec.dataset_file,
            "zip_path": str(loc.zip_path),
            "zip_fingerprint": zip_fp,
            "extracted_at": datetime.now(timezone.utc).isoformat(),
        }
        results[spec.source_id] = "extracted"

    save_manifest(store_dir, manifest)
    return results


def resolve_csv_path(
    store_dir: Path,
    roots: Iterable[Path],
    dataset_file: str,
) -> Path | None:
    """Prefer extracted CSV under store_dir; fall back to on-the-fly path marker."""
    direct = store_dir / dataset_file
    if direct.is_file():
        return direct
    index = build_dataset_index(roots)
    loc = index.get(dataset_file.lower())
    if loc is None:
        return None
    return loc.zip_path  # adapter reads via zip + member
