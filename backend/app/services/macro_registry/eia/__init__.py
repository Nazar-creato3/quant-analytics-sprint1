"""EIA bulk/API macro energy series."""
from app.services.macro_registry.eia.parser import (
    load_bulk_series,
    parse_eia_endpoint,
    parse_eia_series_payload,
)
from app.services.macro_registry.eia.series import EIA_SERIES, eia_endpoint

__all__ = [
    "EIA_SERIES",
    "eia_endpoint",
    "load_bulk_series",
    "parse_eia_endpoint",
    "parse_eia_series_payload",
]
