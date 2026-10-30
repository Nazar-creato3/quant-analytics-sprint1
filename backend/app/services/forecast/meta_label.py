"""Second-stage take/skip. Missing p_beat does not veto the mesh."""

from __future__ import annotations


def meta_label_take(
    *,
    direction: str,
    p_calibrated: float | None,
    mesh_confidence: float,
    strong_mesh: float = 0.72,
) -> bool:
    if p_calibrated is None:
        return True
    aligned = (
        (direction == "long" and p_calibrated >= 0.5)
        or (direction == "short" and p_calibrated <= 0.5)
    )
    if aligned:
        return True
    return float(mesh_confidence) >= strong_mesh
