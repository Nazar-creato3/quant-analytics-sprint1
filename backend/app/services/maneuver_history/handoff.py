"""Control file for prompt 40. This module does not attribute approvals."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SCHEMA = "maneuver_history.control.v1"


def control_document(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "for_prompt": 40,
        "model_version": result.get("model_version"),
        "seed": result.get("seed"),
        "tax_cash_computed": False,
        "target_source": "user",
        "crisis_windows": result.get("crisis_windows"),
        "delistings": result.get("delistings"),
        "leak_failures": result.get("leak_failures"),
        "point_in_time_ok": result.get("point_in_time_ok"),
        "decision_dates": result.get("decision_dates"),
        "scenarios": result.get("scenarios"),
        "parameter_selection": result.get("parameter_selection"),
    }


def write_control_input(result: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(control_document(result), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def read_control_input(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != SCHEMA:
        raise ValueError("schema")
    if data.get("for_prompt") != 40:
        raise ValueError("for_prompt")
    return data
