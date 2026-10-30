"""MLflow model card for research → prod. Local JSON if MLflow is down."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from app.services.alpha.veto import VETO_HIERARCHY
from app.services.forecast.mlflow_registry import register_ensemble_run


@dataclass(frozen=True, slots=True)
class ModelCard:
    name: str
    version: str
    feature_freeze_id: str | None
    feature_lineage: str
    label_recipe: str
    cv_method: str
    horizons: tuple[int, ...]
    veto_hierarchy: tuple[str, ...]
    n_train: int
    metrics: dict[str, float]
    promoted: bool
    created_at: str
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["horizons"] = list(self.horizons)
        d["veto_hierarchy"] = list(self.veto_hierarchy)
        return d


def build_card(
    *,
    name: str,
    metrics: Mapping[str, float],
    n_train: int,
    feature_lineage: str,
    feature_freeze_id: str | None,
    label_recipe: str = "triple_barrier+meta_label",
    cv_method: str = "nested_combinatorial_purged_cv",
    horizons: Sequence[int] = (1, 5, 21),
    promoted: bool = False,
    version: str | None = None,
    note: str = "",
) -> ModelCard:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return ModelCard(
        name=name,
        version=version or stamp,
        feature_freeze_id=feature_freeze_id,
        feature_lineage=feature_lineage,
        label_recipe=label_recipe,
        cv_method=cv_method,
        horizons=tuple(int(h) for h in horizons),
        veto_hierarchy=VETO_HIERARCHY,
        n_train=int(n_train),
        metrics={str(k): float(v) for k, v in metrics.items()},
        promoted=bool(promoted),
        created_at=stamp,
        note=note,
    )


def promote_to_prod(card: ModelCard, *, artifact: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Register + optionally alias live. Requires freeze_id so live == backtest features."""
    if card.promoted and not card.feature_freeze_id:
        raise ValueError("cannot promote without a feature freeze_id (backtest must equal live)")
    result = register_ensemble_run(
        model_name=card.name,
        accuracy=float(card.metrics.get("outer_accuracy") or card.metrics.get("accuracy") or 0.0),
        n=int(card.metrics.get("outer_n") or card.n_train),
        params={
            "label_recipe": card.label_recipe,
            "cv_method": card.cv_method,
            "feature_lineage": card.feature_lineage,
            "feature_freeze_id": card.feature_freeze_id or "",
            "horizons": ",".join(str(h) for h in card.horizons),
            "veto_hierarchy": ">".join(card.veto_hierarchy),
        },
        tags={
            "alpha_factory": "true",
            "label_recipe": card.label_recipe,
            "cv_method": card.cv_method,
        },
        promote_live=card.promoted,
        artifact_dict={"model_card": card.to_dict(), **dict(artifact or {})},
    )
    result["model_card"] = card.to_dict()
    return result


def _cards_dir():
    from pathlib import Path
    import os

    return Path(os.environ.get("MLFLOW_EXPORT_DIR", "/app/data/mlflow_exports"))


def list_research_cards() -> list[dict[str, Any]]:
    folder = _cards_dir()
    if not folder.is_dir():
        return []
    latest = folder / "latest_registry.json"
    if latest.is_file():
        try:
            rows = json.loads(latest.read_text(encoding="utf-8"))
            if isinstance(rows, list):
                return rows
        except (OSError, json.JSONDecodeError):
            pass
    return []


def human_promote(
    card: ModelCard,
    *,
    confirm: bool,
    reviewer: str,
    artifact: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Human notebook/API step. Never auto-promote from retrain."""
    if not confirm:
        raise ValueError("human confirm=True required (read the card first)")
    if not str(reviewer or "").strip():
        raise ValueError("reviewer id required")
    if not card.feature_freeze_id:
        raise ValueError("cannot promote without feature freeze_id")
    outer_n = float(card.metrics.get("outer_n") or card.metrics.get("n") or 0)
    if card.n_train < 20 and outer_n < 20:
        raise ValueError("sample too thin to promote")
    if card.cv_method != "nested_combinatorial_purged_cv":
        raise ValueError(f"refuse promote on cv_method={card.cv_method}")
    if card.label_recipe != "triple_barrier+meta_label":
        raise ValueError(f"refuse promote on label_recipe={card.label_recipe}")
    promoted = ModelCard(
        name=card.name,
        version=card.version,
        feature_freeze_id=card.feature_freeze_id,
        feature_lineage=card.feature_lineage,
        label_recipe=card.label_recipe,
        cv_method=card.cv_method,
        horizons=card.horizons,
        veto_hierarchy=card.veto_hierarchy,
        n_train=card.n_train,
        metrics=card.metrics,
        promoted=True,
        created_at=card.created_at,
        note=f"promoted_by={reviewer.strip()} {card.note}".strip(),
    )
    return promote_to_prod(promoted, artifact=artifact)
