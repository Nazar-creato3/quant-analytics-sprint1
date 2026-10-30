"""Research / alpha factory: multi-horizon labels, CS neutralization, nested CPCV.

Qlib-style operators without a Qlib vendor. Free/already-wired sources only.
"""
from app.services.alpha.books import dual_books, sleeve_to_dict
from app.services.alpha.horizons import ALPHA_HORIZONS, excess_stack, latest_excess_map
from app.services.alpha.labels import primary_labels, stack_primary_labels
from app.services.alpha.model_card import ModelCard, build_card, human_promote, promote_to_prod
from app.services.alpha.nested_cpcv import nested_cpcv_select
from app.services.alpha.neutralization import neutralize_cs
from app.services.alpha.regime_gate import detect_regime
from app.services.alpha.veto import VETO_HIERARCHY, GateInputs, combine as combine_gates

__all__ = [
    "ALPHA_HORIZONS",
    "VETO_HIERARCHY",
    "ModelCard",
    "GateInputs",
    "build_card",
    "combine_gates",
    "detect_regime",
    "dual_books",
    "excess_stack",
    "latest_excess_map",
    "nested_cpcv_select",
    "neutralize_cs",
    "primary_labels",
    "human_promote",
    "promote_to_prod",
    "sleeve_to_dict",
    "stack_primary_labels",
]
