"""Append-only hash chain for forecast_log (Prompt 11A)."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

GENESIS = "0" * 64


def canonical_payload(fields: Mapping[str, Any]) -> str:
    return json.dumps(dict(fields), sort_keys=True, separators=(",", ":"), default=str)


def row_hash(prev_hash: str, fields: Mapping[str, Any]) -> str:
    body = f"{prev_hash}\n{canonical_payload(fields)}"
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def snapshot_hash(row_hashes: list[str]) -> str:
    joined = "\n".join(row_hashes)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()
