"""Point-in-time correct forecast feature store (Feast when available, else local)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from app.core.logging import get_logger

try:
    from app.services.forecast.forecast_features import (
        FORECAST_FEATURE_COLUMNS,
        build_forecast_feature_row,
    )
except ImportError:  # slim CI image has no pandas
    FORECAST_FEATURE_COLUMNS: tuple[str, ...] = ()

    def build_forecast_feature_row(*_a: Any, **_k: Any) -> dict[str, float]:
        raise RuntimeError("pandas is required for forecast features")

logger = get_logger(__name__)

DEFAULT_STORE_DIR = Path("/app/data/feature_store")


@dataclass(frozen=True, slots=True)
class FeatureRow:
    symbol: str
    event_timestamp: datetime
    features: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "event_timestamp": self.event_timestamp.isoformat(),
            "features": self.features,
        }


class ForecastFeatureStore:
    """Offline feature store with point-in-time joins.

    When ``feast`` is installed and a repo is configured, callers can swap to
    Feast retrieval. The default implementation is a local parquet/JSON store
    that never leaks future labels into training rows.

    Pass ``freeze_id`` to read a frozen snapshot so a backtest cannot see
    features that were materialized after the freeze (live == replay).
    """

    def __init__(self, store_dir: Path | None = None, *, freeze_id: str | None = None) -> None:
        live = store_dir or Path(
            __import__("os").environ.get("FEAST_STORE_DIR", str(DEFAULT_STORE_DIR))
        )
        self.live_dir = live
        from app.services.alpha.feature_lineage import resolve_store_dir

        self.freeze_id = freeze_id
        self.store_dir = resolve_store_dir(live, freeze_id) if freeze_id else live
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self._feast = None
        try:
            import feast  # noqa: F401

            self._feast = True
        except Exception:
            self._feast = False

    @property
    def backend(self) -> str:
        # Package presence alone does not mean Feast registry is wired.
        return "local_pit"

    def materialize_from_prices(
        self,
        symbol: str,
        prices: Sequence[float],
        timestamps: Sequence[datetime] | None = None,
        *,
        regime_label: str = "choppy_range",
    ) -> int:
        """Write feature rows at each time index using only past prices (PIT)."""
        if len(prices) < 30:
            return 0
        if timestamps is None:
            now = datetime.now(timezone.utc)
            timestamps = [
                now.replace(hour=0, minute=0, second=0, microsecond=0)
                for _ in prices
            ]
            # synthetic ascending daily stamps ending at today
            from datetime import timedelta

            base = timestamps[-1]
            timestamps = [base - timedelta(days=len(prices) - 1 - i) for i in range(len(prices))]

        rows: list[dict[str, Any]] = []
        for i in range(30, len(prices)):
            window = prices[: i + 1]
            feats = build_forecast_feature_row(window, regime_label=regime_label)
            rows.append(
                {
                    "symbol": symbol.upper(),
                    "event_timestamp": timestamps[i].isoformat(),
                    "features": {c: float(feats[c]) for c in FORECAST_FEATURE_COLUMNS},
                }
            )
        if self.freeze_id:
            raise RuntimeError("refusing to materialize into a frozen feature snapshot")
        path = self._symbol_path(symbol)
        path.write_text(json.dumps(rows), encoding="utf-8")
        from app.services.alpha.feature_lineage import (
            append_materialization,
            build_lineage,
            is_frozen,
            write_manifest,
            write_registry,
        )

        if is_frozen(self.store_dir):
            raise RuntimeError("refusing to materialize into a frozen feature snapshot")
        lin = build_lineage(
            FORECAST_FEATURE_COLUMNS,
            extra={"symbol": symbol.upper(), "n_rows": len(rows)},
        )
        write_manifest(self.store_dir, lin)
        write_registry(self.store_dir, columns=FORECAST_FEATURE_COLUMNS)
        append_materialization(self.store_dir, symbol=symbol.upper(), n_rows=len(rows), lineage=lin)
        return len(rows)

    def freeze(self, freeze_id: str) -> Path:
        from app.services.alpha.feature_lineage import freeze_store

        return freeze_store(self.live_dir, freeze_id)

    def lineage(self):
        from app.services.alpha.feature_lineage import read_manifest

        return read_manifest(self.store_dir)

    def get_historical_features(
        self,
        symbol: str,
        entity_timestamps: Sequence[datetime],
    ) -> list[FeatureRow]:
        """Point-in-time retrieval: for each as-of time, last feature row <= as-of."""
        stored = self._load(symbol)
        if not stored:
            return []
        out: list[FeatureRow] = []
        for ts in entity_timestamps:
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            chosen = None
            for row in stored:
                ets = datetime.fromisoformat(row["event_timestamp"].replace("Z", "+00:00"))
                if ets.tzinfo is None:
                    ets = ets.replace(tzinfo=timezone.utc)
                if ets <= ts:
                    chosen = row
                else:
                    break
            if chosen:
                out.append(
                    FeatureRow(
                        symbol=symbol.upper(),
                        event_timestamp=datetime.fromisoformat(
                            chosen["event_timestamp"].replace("Z", "+00:00")
                        ),
                        features={k: float(v) for k, v in chosen["features"].items()},
                    )
                )
        return out

    def latest_features(self, symbol: str) -> FeatureRow | None:
        stored = self._load(symbol)
        if not stored:
            return None
        row = stored[-1]
        return FeatureRow(
            symbol=symbol.upper(),
            event_timestamp=datetime.fromisoformat(row["event_timestamp"].replace("Z", "+00:00")),
            features={k: float(v) for k, v in row["features"].items()},
        )

    def feature_matrix(
        self,
        symbol: str,
        *,
        as_of: datetime | None = None,
    ) -> tuple[np.ndarray, list[str]]:
        row = None
        if as_of is not None:
            got = self.get_historical_features(symbol, [as_of])
            row = got[0] if got else None
        else:
            row = self.latest_features(symbol)
        if row is None:
            return np.zeros((1, len(FORECAST_FEATURE_COLUMNS))), list(FORECAST_FEATURE_COLUMNS)
        X = np.array([[row.features.get(c, 0.0) for c in FORECAST_FEATURE_COLUMNS]])
        return X, list(FORECAST_FEATURE_COLUMNS)

    def _symbol_path(self, symbol: str) -> Path:
        return self.store_dir / f"{symbol.upper()}.json"

    def _load(self, symbol: str) -> list[dict[str, Any]]:
        path = self._symbol_path(symbol)
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception as exc:
            logger.warning("feature_store_load_failed", symbol=symbol, error=str(exc))
            return []


_STORE: ForecastFeatureStore | None = None


def get_forecast_feature_store() -> ForecastFeatureStore:
    global _STORE
    if _STORE is None:
        _STORE = ForecastFeatureStore()
    return _STORE


def feast_status() -> Mapping[str, Any]:
    """Public feature-store status without vendor or package names."""
    store = get_forecast_feature_store()
    return {
        "backend": "local",
        "ready": True,
        "freeze_id": store.freeze_id,
        "feature_count": len(FORECAST_FEATURE_COLUMNS),
        "note": "Хранилище признаков доступно.",
    }
