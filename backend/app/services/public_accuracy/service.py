"""Public copy of the forecast journal. It does not compute a second accuracy."""
from __future__ import annotations

from typing import Any

from app.services.forecast_log.hash_chain import snapshot_hash
from app.services.forecast_log.store import get_store
from app.services.forecast_log.summary import internal_summary
from app.services.qa.feature_flags import is_enabled

_MISSING = "нет данных"


def journal_digest() -> str:
    return snapshot_hash([row.row_hash for row in get_store().rows()])


def verify_journal(digest: str) -> bool:
    return digest == journal_digest()


def public_accuracy() -> dict[str, Any]:
    if not is_enabled("qa_public_accuracy"):
        return {"status": "off"}
    summary = internal_summary()
    snapshots = summary["snapshots"]
    horizons = []
    for row in summary["horizons"]:
        horizons.append(
            {
                "horizon_days": str(row["horizon_days"]),
                "n": str(row["n"]),
                "hits": str(row["hits"]),
                "accuracy": str(row["accuracy"]),
                "ci_low": str(row["ci_low"]),
                "ci_high": str(row["ci_high"]),
                "naive_accuracy": str(row["naive_accuracy"]),
            }
        )
    empty = not horizons
    return {
        "status": "ok",
        "accuracy": _MISSING if empty else horizons[0]["accuracy"],
        "ci_low": _MISSING if empty else horizons[0]["ci_low"],
        "ci_high": _MISSING if empty else horizons[0]["ci_high"],
        "naive": _MISSING if empty else horizons[0]["naive_accuracy"],
        "by_instrument": _MISSING,
        "weak_periods": _MISSING,
        "updated": next(iter(snapshots), _MISSING) if snapshots else _MISSING,
        "emissions": str(summary["emissions"]),
        "settlements": str(summary["settlements"]),
        "horizons": horizons,
        "digest": journal_digest(),
    }
