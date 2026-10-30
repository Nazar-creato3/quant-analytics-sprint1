"""Portfolio risk status for dashboard indicator (ControlBar)."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints.settings import _defaults as settings_defaults
from app.core.config import settings
from app.schemas.portfolio import RiskStatusOut
from app.services.portfolio.metrics import build_portfolio_metrics
from app.utils.cache import cache_get
from app.utils.helpers import get_user_settings_key

# Thresholds aligned with cockpit ControlBar semantics.
_EXPOSURE_CAUTION_PCT = 50.0
_EXPOSURE_BLOCK_PCT = 70.0
_CASH_BUFFER_CAUTION_RATIO = 0.75  # warn when free cash < 75% of required buffer


async def _user_daily_max_loss_pct(email: str) -> float:
    key = get_user_settings_key(email)
    stored = await cache_get(key)
    merged = {**settings_defaults(), **(stored or {})}
    return float(merged.get("daily_max_loss_pct", settings.DAILY_MAX_LOSS_PCT))


def _level_label(level: str) -> str:
    return {"ok": "В норме", "caution": "Внимание", "block": "Лимит"}.get(level, "—")


def _compute_level(
    *,
    exposure_pct: float,
    max_exposure_pct: float,
    balance_usd: float,
    cash_buffer_usd: float,
) -> str:
    effective_max = max_exposure_pct if max_exposure_pct > 0 else settings.MAX_PORTFOLIO_EXPOSURE_PCT

    if exposure_pct >= effective_max or exposure_pct >= _EXPOSURE_BLOCK_PCT:
        return "block"

    if exposure_pct >= _EXPOSURE_CAUTION_PCT or exposure_pct >= effective_max * 0.625:
        return "caution"

    if cash_buffer_usd > 0 and balance_usd < cash_buffer_usd * _CASH_BUFFER_CAUTION_RATIO:
        return "caution"

    return "ok"


def _build_explanation(
    *,
    level: str,
    exposure_pct: float,
    max_exposure_pct: float,
    daily_max_loss_pct: float,
    open_maneuvers: int,
    trading_usd: float,
    balance_usd: float,
    cash_buffer_usd: float,
) -> tuple[str, list[str]]:
    effective_max = max_exposure_pct if max_exposure_pct > 0 else settings.MAX_PORTFOLIO_EXPOSURE_PCT
    factors: list[str] = []

    factors.append(
        f"Экспозиция портфеля: {exposure_pct:.1f}% "
        f"(лимит {effective_max:.0f}%, в сделках ${trading_usd:,.0f})."
    )

    if open_maneuvers > 0:
        factors.append(f"Открыто позиций: {open_maneuvers}.")
    elif trading_usd > 0:
        factors.append(
            f"В сделках ${trading_usd:,.0f} (grid-боты или позиции вне маневров)."
        )
    else:
        factors.append("Открытых позиций нет — капитал полностью в кэше.")

    factors.append(
        f"Дневной лимит убытка: {daily_max_loss_pct:.1f}% "
        f"(настройка профиля, не текущий P&L)."
    )

    if cash_buffer_usd > 0:
        buffer_pct = balance_usd / cash_buffer_usd * 100 if cash_buffer_usd else 100.0
        factors.append(
            f"Свободный кэш ${balance_usd:,.0f} — "
            f"{buffer_pct:.0f}% от обязательного буфера ${cash_buffer_usd:,.0f}."
        )

    if level == "block":
        if exposure_pct >= effective_max:
            headline = (
                f"Экспозиция {exposure_pct:.1f}% достигла или превысила лимит "
                f"{effective_max:.0f}%. Новые сделки могут быть заблокированы RiskGate."
            )
        else:
            headline = (
                f"Экспозиция {exposure_pct:.1f}% выше критического порога "
                f"{_EXPOSURE_BLOCK_PCT:.0f}%. Рекомендуется сократить позиции."
            )
    elif level == "caution":
        reasons: list[str] = []
        if exposure_pct >= _EXPOSURE_CAUTION_PCT:
            reasons.append(f"экспозиция {exposure_pct:.1f}% выше {_EXPOSURE_CAUTION_PCT:.0f}%")
        elif exposure_pct >= effective_max * 0.625:
            reasons.append(
                f"экспозиция {exposure_pct:.1f}% превышает 62.5% лимита ({effective_max:.0f}%)"
            )
        if cash_buffer_usd > 0 and balance_usd < cash_buffer_usd * _CASH_BUFFER_CAUTION_RATIO:
            reasons.append("свободный кэш ниже обязательного буфера")
        detail = ", ".join(reasons) if reasons else "приближение к лимитам"
        headline = f"Требует внимания: {detail}. Проверьте открытые позиции перед новыми сделками."
    else:
        headline = (
            f"Риск в норме: экспозиция {exposure_pct:.1f}% в пределах лимита "
            f"{effective_max:.0f}%, кэш-буфер соблюдён."
        )

    return headline, factors


async def build_risk_status(email: str, db: AsyncSession) -> RiskStatusOut:
    """Compute live portfolio risk level and Russian explanation for the dashboard."""
    metrics = await build_portfolio_metrics(email, db)
    daily_max_loss_pct = await _user_daily_max_loss_pct(email)

    level = _compute_level(
        exposure_pct=metrics.exposure_pct,
        max_exposure_pct=metrics.max_exposure_pct,
        balance_usd=metrics.balance_usd,
        cash_buffer_usd=metrics.cash_buffer_usd,
    )
    explanation, factors = _build_explanation(
        level=level,
        exposure_pct=metrics.exposure_pct,
        max_exposure_pct=metrics.max_exposure_pct,
        daily_max_loss_pct=daily_max_loss_pct,
        open_maneuvers=metrics.open_maneuvers,
        trading_usd=metrics.trading_usd,
        balance_usd=metrics.balance_usd,
        cash_buffer_usd=metrics.cash_buffer_usd,
    )

    return RiskStatusOut(
        level=level,
        label=_level_label(level),
        explanation=explanation,
        contributing_factors=factors,
        exposure_pct=metrics.exposure_pct,
        max_exposure_pct=metrics.max_exposure_pct,
        daily_max_loss_pct=daily_max_loss_pct,
        open_maneuvers=metrics.open_maneuvers,
        trading_usd=metrics.trading_usd,
        cash_buffer_usd=metrics.cash_buffer_usd,
        as_of=metrics.as_of or datetime.now(timezone.utc).isoformat(),
    )
