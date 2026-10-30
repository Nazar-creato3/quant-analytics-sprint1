"""ML model drift monitoring for maneuver signals (spec A.7)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import Maneuver, ManeuverStatus, StrategyType

logger = get_logger(__name__)

DRIFT_ALERT_THRESHOLD = 0.12


@dataclass
class ModelDriftSnapshot:
    live_accuracy: float | None
    backtest_accuracy: float | None
    accuracy_gap: float | None
    calibration_error: float | None
    per_regime: dict[str, float]
    alert: bool
    alert_message: str | None
    as_of: str

    def to_dict(self) -> dict:
        return {
            "live_accuracy": self.live_accuracy,
            "backtest_accuracy": self.backtest_accuracy,
            "accuracy_gap": self.accuracy_gap,
            "calibration_error": self.calibration_error,
            "per_regime": self.per_regime,
            "alert": self.alert,
            "alert_message": self.alert_message,
            "as_of": self.as_of,
        }


def empty_model_drift() -> ModelDriftSnapshot:
    return ModelDriftSnapshot(
        live_accuracy=None,
        backtest_accuracy=None,
        accuracy_gap=None,
        calibration_error=None,
        per_regime={},
        alert=False,
        alert_message=None,
        as_of=datetime.now(timezone.utc).isoformat(),
    )


async def _live_direction_accuracy(
    db: AsyncSession,
    *,
    owner_user_id: str,
) -> tuple[float | None, dict[str, float]]:
    if not owner_user_id:
        return None, {}
    from app.db.models import ManeuverReport

    result = await db.execute(
        select(Maneuver)
        .join(ManeuverReport, Maneuver.report_id == ManeuverReport.id)
        .where(
            Maneuver.strategy_type != StrategyType.NO_TRADE,
            Maneuver.status.in_([ManeuverStatus.FILLED, ManeuverStatus.CANCELLED]),
            Maneuver.realized_pnl.isnot(None),
            ManeuverReport.created_by == owner_user_id,
        )
    )
    rows = result.scalars().all()
    if not rows:
        return None, {}

    correct = 0
    total = 0
    per_regime: dict[str, list[bool]] = {}

    for m in rows:
        pnl = float(m.realized_pnl or 0)
        if m.direction == "long":
            hit = pnl > 0
        elif m.direction == "short":
            hit = pnl > 0
        else:
            continue
        total += 1
        if hit:
            correct += 1
        regime = "unknown"
        if m.source_signals and isinstance(m.source_signals, list):
            pass
        per_regime.setdefault(regime, []).append(hit)

    live_acc = round(correct / total, 4) if total >= 5 else None
    regime_acc = {
        k: round(sum(1 for x in v if x) / len(v), 4)
        for k, v in per_regime.items()
        if len(v) >= 3
    }
    return live_acc, regime_acc


async def compute_model_drift(db: AsyncSession, *, owner_user_id: str) -> ModelDriftSnapshot:
    """Compare live signal accuracy vs backtest benchmark; alert on meaningful gap."""
    if not owner_user_id:
        return empty_model_drift()
    live_acc, per_regime = await _live_direction_accuracy(db, owner_user_id=owner_user_id)

    backtest_acc = None
    try:
        from app.services.track_record.service import TrackRecordService

        tr = TrackRecordService().get_public_summary().to_dict()
        if tr and tr.get("aggregate"):
            backtest_acc = tr["aggregate"].get("direction_accuracy") or tr["aggregate"].get("win_rate")
    except Exception as exc:
        logger.debug("Track record for drift skipped", error=str(exc))

    gap = None
    alert = False
    alert_message = None
    if live_acc is not None and backtest_acc is not None:
        gap = round(backtest_acc - live_acc, 4)
        if gap >= DRIFT_ALERT_THRESHOLD:
            alert = True
            alert_message = (
                f"Live accuracy ({live_acc:.0%}) ниже backtest ({backtest_acc:.0%}) "
                f"на {gap:.0%} — возможен drift модели."
            )

    calibration_error = None
    try:
        from app.services.prediction_hierarchy.calibration_tracker import get_live_calibration_error

        calibration_error = get_live_calibration_error()
        if calibration_error is not None and calibration_error > 0.15:
            alert = True
            msg = f"Calibration error {calibration_error:.2f} выше порога."
            alert_message = f"{alert_message}; {msg}" if alert_message else msg
    except Exception:
        pass

    if alert and alert_message and settings.telegram_configured:
        try:
            from app.services.alerts.telegram import send_telegram_message

            await send_telegram_message(
                settings.TELEGRAM_CHAT_ID,
                f"⚠️ Apex signal drift: {alert_message}",
            )
        except Exception as exc:
            logger.warning("Drift telegram alert failed", error=str(exc))

    return ModelDriftSnapshot(
        live_accuracy=live_acc,
        backtest_accuracy=backtest_acc,
        accuracy_gap=gap,
        calibration_error=calibration_error,
        per_regime=per_regime,
        alert=alert,
        alert_message=alert_message,
        as_of=datetime.now(timezone.utc).isoformat(),
    )
