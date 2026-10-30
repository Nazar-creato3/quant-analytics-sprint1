"""MLflow tracking for forecast ensemble baselines and challengers."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.utils.wilson_ci import wilson_ci_from_rate

logger = get_logger(__name__)

EXPERIMENT_NAME = "forecast_ensemble"
BASELINE_ALIAS = "live_baseline"
CANONICAL_BASELINE = "ensemble_baseline_v1"


def _export_dir() -> Path:
    return Path(os.environ.get("MLFLOW_EXPORT_DIR", "/app/data/mlflow_exports"))


@dataclass(frozen=True, slots=True)
class ModelAccuracyMetrics:
    model_name: str
    version: str
    accuracy: float
    n: int
    ci_low: float
    ci_high: float
    is_live: bool
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _tracking_uri() -> str:
    return (
        os.environ.get("MLFLOW_TRACKING_URI")
        or getattr(__import__("app.core.config", fromlist=["get_settings"]).get_settings(), "MLFLOW_TRACKING_URI", "")
        or "file:///app/data/mlflow"
    )


def mlflow_available() -> bool:
    try:
        import mlflow  # noqa: F401

        return True
    except Exception:
        return False


def register_ensemble_run(
    *,
    model_name: str,
    accuracy: float,
    n: int,
    params: dict[str, Any] | None = None,
    tags: dict[str, str] | None = None,
    promote_live: bool = False,
    artifact_dict: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Log a forecast model run to MLflow (file store or tracking server)."""
    ci = wilson_ci_from_rate(accuracy, n) if n > 0 else None
    ci_low = float(ci.ci_low) if ci else 0.0
    ci_high = float(ci.ci_high) if ci else 1.0
    result = {
        "model_name": model_name,
        "accuracy": accuracy,
        "n": n,
        "ci_low": ci_low,
        "ci_high": ci_high,
        "is_live": promote_live,
        "mlflow": False,
        "run_id": None,
    }
    if not mlflow_available():
        _write_local_export(result, params=params, artifact_dict=artifact_dict)
        logger.warning("mlflow_unavailable_local_export", model=model_name)
        return result

    try:
        import mlflow
        from mlflow.tracking import MlflowClient

        uri = _tracking_uri()
        mlflow.set_tracking_uri(uri)
        mlflow.set_experiment(EXPERIMENT_NAME)
        with mlflow.start_run(run_name=f"{model_name}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}") as run:
            mlflow.log_params({k: str(v)[:250] for k, v in (params or {}).items()})
            mlflow.log_metrics(
                {
                    "direction_accuracy": float(accuracy),
                    "sample_size": float(n),
                    "wilson_ci_low": ci_low,
                    "wilson_ci_high": ci_high,
                }
            )
            tag_payload = {"model_family": model_name, **(tags or {})}
            if promote_live:
                tag_payload["live"] = "true"
                tag_payload["alias"] = BASELINE_ALIAS
            for k, v in tag_payload.items():
                mlflow.set_tag(k, v)
            if artifact_dict:
                tmp = _export_dir() / "tmp_artifacts"
                tmp.mkdir(parents=True, exist_ok=True)
                path = tmp / f"{model_name}_metrics.json"
                path.write_text(json.dumps(artifact_dict, indent=2, default=str), encoding="utf-8")
                mlflow.log_artifact(str(path))
            result["mlflow"] = True
            result["run_id"] = run.info.run_id
            result["tracking_uri"] = uri

            if promote_live:
                client = MlflowClient()
                try:
                    for info in client.search_runs(
                        experiment_ids=[run.info.experiment_id],
                        filter_string="tags.live = 'true'",
                        max_results=50,
                    ):
                        if info.info.run_id != run.info.run_id:
                            client.set_tag(info.info.run_id, "live", "false")
                except Exception as exc:
                    logger.debug("mlflow_clear_live_tags_failed", error=str(exc))
    except Exception as exc:
        logger.warning("mlflow_server_unavailable_local_export", model=model_name, error=str(exc)[:300])
        result["mlflow"] = False
        result["run_id"] = None
        result["mlflow_error"] = str(exc)[:300]

    _write_local_export(result, params=params, artifact_dict=artifact_dict)
    return result


def _write_local_export(
    result: dict[str, Any],
    *,
    params: dict[str, Any] | None,
    artifact_dict: dict[str, Any] | None,
) -> Path:
    export_dir = _export_dir()
    export_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = export_dir / f"{result['model_name']}_{stamp}.json"
    payload = {
        "exported_at": stamp,
        "result": result,
        "params": params or {},
        "artifact": artifact_dict or {},
    }
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    latest = export_dir / "latest_registry.json"
    registry: list[dict[str, Any]] = []
    if latest.exists():
        try:
            registry = json.loads(latest.read_text(encoding="utf-8"))
        except Exception:
            registry = []
    if not isinstance(registry, list):
        registry = []
    # Drop meaningless empty evaluations (n=0) — they must not pollute the registry.
    registry = [row for row in registry if int(row.get("n") or 0) > 0]
    # demote previous live
    if result.get("is_live"):
        for row in registry:
            row["is_live"] = False
    registry.append(
        {
            "model_name": result["model_name"],
            "version": result.get("run_id") or stamp,
            "accuracy": result["accuracy"],
            "n": result["n"],
            "ci_low": result["ci_low"],
            "ci_high": result["ci_high"],
            "is_live": bool(result.get("is_live")),
            "exported_at": stamp,
            "path": str(path.name),
        }
    )
    latest.write_text(json.dumps(registry, indent=2), encoding="utf-8")
    _sync_docs_mirror(registry)
    return path


def _docs_mirror_path() -> Path:
    return Path(__file__).resolve().parents[4] / "docs" / "mlflow_latest_registry.json"


def _sync_docs_mirror(registry: list[dict[str, Any]]) -> None:
    """Keep docs/mlflow_latest_registry.json aligned with runtime export (source of truth)."""
    if os.environ.get("MLFLOW_SYNC_DOCS", "true").lower() in {"0", "false", "no"}:
        return
    try:
        path = _docs_mirror_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(registry, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.debug("mlflow_docs_mirror_skipped", error=str(exc))


def write_canonical_registry() -> list[dict[str, Any]]:
    """Rebuild registry from known production truth; exactly one is_live row."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    rows: list[dict[str, Any]] = [
        {
            "model_name": CANONICAL_BASELINE,
            "version": "live_prod_baseline",
            "accuracy": 0.433,
            "n": 561,
            "ci_low": 0.393,
            "ci_high": 0.474,
            "is_live": True,
            "exported_at": stamp,
            "path": "ensemble_baseline_v1_live_prod_baseline.json",
            "note": "Live production direction baseline (resolver-backed)",
        },
        {
            "model_name": "forecast_stacking_meta",
            "version": "20260809T142707Z",
            "accuracy": 0.7728119180633147,
            "n": 1074,
            "ci_low": 0.7468052347861015,
            "ci_high": 0.7968739106467709,
            "is_live": False,
            "exported_at": "20260809T142707Z",
            "path": "forecast_stacking_meta_20260809T142707Z.json",
            "note": "Ensemble member (stacking meta); not the live baseline alias",
        },
        {
            "model_name": "chronos_t5_tiny",
            "version": "20260809T150149Z",
            "accuracy": 0.43478260869565216,
            "n": 20,
            "ci_low": 0.25819502085709295,
            "ci_high": 0.6579179916924003,
            "is_live": False,
            "exported_at": "20260809T150149Z",
            "path": "chronos_t5_tiny_20260809T150149Z.json",
            "note": "Ensemble member; rolling eval n=20",
        },
    ]
    export_dir = _export_dir()
    export_dir.mkdir(parents=True, exist_ok=True)
    latest = export_dir / "latest_registry.json"
    latest.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    _sync_docs_mirror(rows)
    if mlflow_available():
        try:
            import mlflow

            uri = _tracking_uri()
            mlflow.set_tracking_uri(uri)
            mlflow.set_experiment(EXPERIMENT_NAME)
            with mlflow.start_run(run_name=f"{CANONICAL_BASELINE}-canonical") as run:
                mlflow.log_metrics(
                    {
                        "direction_accuracy": 0.433,
                        "sample_size": 561.0,
                        "wilson_ci_low": 0.393,
                        "wilson_ci_high": 0.474,
                    }
                )
                mlflow.set_tag("live", "true")
                mlflow.set_tag("alias", BASELINE_ALIAS)
                logger.info("mlflow_canonical_baseline_logged", run_id=run.info.run_id)
        except Exception as exc:
            logger.debug("mlflow_canonical_register_skipped", error=str(exc))
    return rows


def list_registered_models() -> list[ModelAccuracyMetrics]:
    latest = _export_dir() / "latest_registry.json"
    if not latest.exists():
        return []
    try:
        rows = json.loads(latest.read_text(encoding="utf-8"))
    except Exception:
        return []
    out: list[ModelAccuracyMetrics] = []
    for row in rows if isinstance(rows, list) else []:
        if int(row.get("n") or 0) <= 0:
            continue
        out.append(
            ModelAccuracyMetrics(
                model_name=str(row.get("model_name")),
                version=str(row.get("version")),
                accuracy=float(row.get("accuracy") or 0),
                n=int(row.get("n") or 0),
                ci_low=float(row.get("ci_low") or 0),
                ci_high=float(row.get("ci_high") or 1),
                is_live=bool(row.get("is_live")),
                note=str(row.get("path") or ""),
            )
        )
    return out


def export_registry_markdown() -> str:
    rows = list_registered_models()
    lines = [
        "# Forecast model registry",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "| Model | Version | Accuracy | Wilson CI | n | Live |",
        "|---|---|---:|---|---:|:---:|",
    ]
    for r in rows:
        live = "YES" if r.is_live else ""
        lines.append(
            f"| {r.model_name} | {r.version[:12]} | {r.accuracy:.1%} | "
            f"[{r.ci_low:.1%}, {r.ci_high:.1%}] | {r.n} | {live} |"
        )
    if not rows:
        lines.append("| _(empty)_ | | | | | |")
    return "\n".join(lines) + "\n"
