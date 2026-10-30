"""Eurostat SDMX-CSV bulk export parsing and catalog."""

from app.services.macro_registry.eurostat.indicators import (
    EUROSTAT_INDICATORS,
    EurostatIndicatorSpec,
    eurostat_bulk_endpoint,
)

__all__ = [
    "EUROSTAT_INDICATORS",
    "EurostatIndicatorSpec",
    "eurostat_bulk_endpoint",
]
