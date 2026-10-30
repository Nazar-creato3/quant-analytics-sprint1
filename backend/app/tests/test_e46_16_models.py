"""E46-16: model cards; compute_regime / historical_var_es off production paths."""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SERVICES = REPO / "backend" / "app" / "services"
MODELS = REPO / "docs" / "models"


def test_e46_16_model_cards_exist_for_production_models():
    names = {
        p.name
        for p in MODELS.glob("*.md")
        if p.name.lower() != "readme.md"
    }
    required = {
        "forecast_core.heuristic.v1.md",
        "forecast_core.stacking.md",
        "forecast_core.lob.md",
        "market_regime.v1.md",
        "risk_engine.fhs.v1.md",
    }
    assert required <= names


def test_e46_16_services_do_not_import_compute_regime():
    hits: list[str] = []
    for path in SERVICES.rglob("*.py"):
        if path.name == "features.py" and path.parent.name == "ml":
            continue
        text = path.read_text(encoding="utf-8")
        if "from app.services.ml.features import compute_regime" in text or "compute_regime," in text:
            hits.append(str(path.relative_to(REPO)).replace("\\", "/"))
    assert hits == []


def test_e46_16_historical_var_es_only_shadow_and_definition():
    hits: list[str] = []
    allowed = {
        "backend/app/services/risk/portfolio_math/var.py",
        "backend/app/services/risk/portfolio_math/__init__.py",
        "backend/app/services/risk_engine/shadow.py",
    }
    for path in SERVICES.rglob("*.py"):
        rel = str(path.relative_to(REPO)).replace("\\", "/")
        if rel in allowed:
            continue
        text = path.read_text(encoding="utf-8")
        if "historical_var_es" in text:
            hits.append(rel)
    assert hits == []
