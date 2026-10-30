"""Eurostat bulk SDMX-CSV adapter for macro registry."""
from __future__ import annotations

from pathlib import Path

import httpx

from app.core.config import _REPO_ROOT, settings
from app.services.macro_registry.adapters.base import IMacroAdapter, build_raw_response
from app.services.macro_registry.eurostat.bulk import discover_data_roots
from app.services.macro_registry.eurostat.indicators import spec_by_id
from app.services.macro_registry.eurostat.parser import (
    build_stream_payload_marker,
    csv_source_fingerprint,
    load_spec_csv,
    observations_for_spec,
    parse_eurostat_endpoint,
    parse_sdmx_csv_bytes,
    parse_stream_payload_marker,
    should_stream_spec_csv,
)
from app.services.macro_registry.types import InternalObservation, RawResponse


class EurostatBulkAdapter(IMacroAdapter):
    """Load curated Eurostat indicators from extracted CSV or local ESTAT zips."""

    async def fetch(self, client: httpx.AsyncClient) -> RawResponse:
        del client
        spec_id = parse_eurostat_endpoint(self.config.endpoint)
        if spec_id is None:
            raise ValueError(f"Unsupported Eurostat endpoint: {self.config.endpoint}")

        spec = spec_by_id(spec_id)
        if spec is None:
            raise ValueError(f"Unknown Eurostat spec_id: {spec_id}")

        store_dir = Path(settings.EUROSTAT_STORE_DIR)
        roots = discover_data_roots(settings.EUROSTAT_DATA_DIR, _REPO_ROOT)

        if should_stream_spec_csv(store_dir=store_dir, roots=roots, spec=spec):
            fingerprint = csv_source_fingerprint(store_dir=store_dir, roots=roots, spec=spec)
            marker = build_stream_payload_marker(spec_id=spec_id, fingerprint=fingerprint)
            return build_raw_response(
                self.config,
                marker,
                content_type="application/x-eurostat-stream",
            )

        payload = load_spec_csv(store_dir=store_dir, roots=roots, spec=spec)
        if payload is None:
            raise FileNotFoundError(
                f"No Eurostat dataset {spec.dataset_file} for {spec_id} "
                f"(EUROSTAT_DATA_DIR={settings.EUROSTAT_DATA_DIR!r})"
            )
        return build_raw_response(
            self.config,
            payload.decode("utf-8-sig", errors="replace"),
            content_type="text/csv",
        )

    def normalize(self, raw: RawResponse) -> list[InternalObservation]:
        spec_id = parse_eurostat_endpoint(self.config.endpoint)
        if spec_id is None:
            return []
        spec = spec_by_id(spec_id)
        if spec is None:
            return []

        stream_spec_id = parse_stream_payload_marker(raw.payload)
        if stream_spec_id is not None:
            if stream_spec_id != spec_id:
                raise ValueError(
                    f"Stream marker spec_id {stream_spec_id!r} != endpoint {spec_id!r}"
                )
            store_dir = Path(settings.EUROSTAT_STORE_DIR)
            roots = discover_data_roots(settings.EUROSTAT_DATA_DIR, _REPO_ROOT)
            return observations_for_spec(
                store_dir=store_dir,
                roots=roots,
                spec_id=spec_id,
            )

        return parse_sdmx_csv_bytes(raw.payload.encode("utf-8"), spec=spec)
