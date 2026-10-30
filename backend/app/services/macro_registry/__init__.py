"""Macro Registry package — source registry, adapters, normalization, reports."""
from app.services.macro_registry.service import MacroRegistryService, load_macro_snapshot

__all__ = ["MacroRegistryService", "load_macro_snapshot"]
