"""Versioned feature snapshots: lineage hash + freeze so backtest == live."""
from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = "alpha_features_v1"
ENTITY = "symbol"
FEATURE_VIEW = "forecast_tech"
TTL_SECONDS = 86400 * 7


@dataclass(frozen=True, slots=True)
class FeatureLineage:
    schema_version: str
    columns: tuple[str, ...]
    transform_id: str
    content_hash: str
    frozen_at: str | None
    freeze_id: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "columns": list(self.columns),
            "transform_id": self.transform_id,
            "content_hash": self.content_hash,
            "frozen_at": self.frozen_at,
            "freeze_id": self.freeze_id,
        }


def lineage_hash(columns: Sequence[str], extra: Mapping[str, Any] | None = None) -> str:
    payload = {"columns": list(columns), "extra": dict(extra or {}), "schema": SCHEMA_VERSION}
    blob = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def build_lineage(
    columns: Sequence[str],
    *,
    transform_id: str = SCHEMA_VERSION,
    extra: Mapping[str, Any] | None = None,
    freeze_id: str | None = None,
) -> FeatureLineage:
    return FeatureLineage(
        schema_version=SCHEMA_VERSION,
        columns=tuple(columns),
        transform_id=transform_id,
        content_hash=lineage_hash(columns, extra),
        frozen_at=datetime.now(timezone.utc).isoformat() if freeze_id else None,
        freeze_id=freeze_id,
    )


def write_manifest(store_dir: Path, lineage: FeatureLineage) -> Path:
    store_dir.mkdir(parents=True, exist_ok=True)
    path = store_dir / "lineage.json"
    path.write_text(json.dumps(lineage.to_dict(), indent=2), encoding="utf-8")
    return path


def read_manifest(store_dir: Path) -> FeatureLineage | None:
    path = store_dir / "lineage.json"
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    cols = tuple(str(c) for c in (raw.get("columns") or ()))
    return FeatureLineage(
        schema_version=str(raw.get("schema_version") or SCHEMA_VERSION),
        columns=cols,
        transform_id=str(raw.get("transform_id") or SCHEMA_VERSION),
        content_hash=str(raw.get("content_hash") or ""),
        frozen_at=raw.get("frozen_at"),
        freeze_id=raw.get("freeze_id"),
    )


def freeze_store(live_dir: Path, freeze_id: str) -> Path:
    dest = live_dir / "freeze" / freeze_id
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    for src in live_dir.glob("*.json"):
        shutil.copy2(src, dest / src.name)
    lin = read_manifest(live_dir) or build_lineage((), freeze_id=freeze_id)
    frozen = FeatureLineage(
        schema_version=lin.schema_version,
        columns=lin.columns,
        transform_id=lin.transform_id,
        content_hash=lin.content_hash,
        frozen_at=datetime.now(timezone.utc).isoformat(),
        freeze_id=freeze_id,
    )
    write_manifest(dest, frozen)
    write_manifest(live_dir, frozen)
    lock = {
        "freeze_id": freeze_id,
        "frozen_at": frozen.frozen_at,
        "content_hash": frozen.content_hash,
        "feature_view": FEATURE_VIEW,
        "entity": ENTITY,
        "ttl_seconds": TTL_SECONDS,
        "backend": "local_pit_feast_shaped",
    }
    (dest / "FROZEN").write_text(json.dumps(lock, indent=2), encoding="utf-8")
    write_registry(dest, columns=frozen.columns, freeze_id=freeze_id)
    write_registry(live_dir, columns=frozen.columns, freeze_id=freeze_id)
    return dest


def write_registry(
    store_dir: Path,
    *,
    columns: Sequence[str],
    freeze_id: str | None = None,
) -> Path:
    store_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "project": "apex_alpha",
        "backend": "local_pit_feast_shaped",
        "entities": [{"name": ENTITY, "join_keys": ["symbol"]}],
        "feature_views": [
            {
                "name": FEATURE_VIEW,
                "entities": [ENTITY],
                "ttl_seconds": TTL_SECONDS,
                "columns": list(columns),
                "schema_version": SCHEMA_VERSION,
            }
        ],
        "freeze_id": freeze_id,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    path = store_dir / "registry.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def append_materialization(
    store_dir: Path,
    *,
    symbol: str,
    n_rows: int,
    lineage: FeatureLineage,
) -> None:
    path = store_dir / "materializations.jsonl"
    row = {
        "event": "materialize",
        "feature_view": FEATURE_VIEW,
        "entity": ENTITY,
        "symbol": symbol,
        "n_rows": n_rows,
        "content_hash": lineage.content_hash,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def is_frozen(store_dir: Path) -> bool:
    return (store_dir / "FROZEN").is_file()


def read_registry(store_dir: Path) -> dict[str, Any] | None:
    path = store_dir / "registry.json"
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def resolve_store_dir(live_dir: Path, freeze_id: str | None) -> Path:
    if not freeze_id:
        return live_dir
    frozen = live_dir / "freeze" / freeze_id
    if not frozen.is_dir():
        raise FileNotFoundError(f"feature freeze {freeze_id!r} missing under {live_dir}")
    return frozen
