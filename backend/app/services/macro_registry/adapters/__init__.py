"""Macro data source adapters (Prompt 42/49)."""
from app.services.macro_registry.adapters.base import IMacroAdapter
from app.services.macro_registry.adapters.calendar import MacroCalendarAdapter
from app.services.macro_registry.adapters.central_bank import CentralBankAdapter
from app.services.macro_registry.adapters.eia_bulk import EiaBulkAdapter
from app.services.macro_registry.adapters.energy import EnergyAdapter
from app.services.macro_registry.adapters.statistics import MacroStatisticsAdapter
from app.services.macro_registry.adapters.eurostat_bulk import EurostatBulkAdapter
from app.services.macro_registry.adapters.world_bank import WorldBankAdapter

__all__ = [
    "IMacroAdapter",
    "CentralBankAdapter",
    "MacroStatisticsAdapter",
    "EnergyAdapter",
    "EiaBulkAdapter",
    "EurostatBulkAdapter",
    "MacroCalendarAdapter",
    "WorldBankAdapter",
]
