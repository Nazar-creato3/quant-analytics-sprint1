"""Portfolio-level risk overlay for maneuver presentation (spec A.5)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.services.macro.sector_seed import sector_for_symbol
from app.services.risk.maneuver_diversification import _factor_vector, cosine_similarity

if TYPE_CHECKING:
    from app.services.risk.maneuver_generator import ManeuverCandidate
    from app.services.risk.engine import PortfolioState

SECTOR_CONCENTRATION_LIMIT = 3
FACTOR_OVERLAP_WARN = 0.75


@dataclass
class PortfolioOverlayResult:
    warnings: list[str] = field(default_factory=list)
    sector: str = "unknown"
    max_factor_overlap: float = 0.0
    sector_count_after_add: int = 0

    @property
    def has_warnings(self) -> bool:
        return bool(self.warnings)


def _sector(ticker: str) -> str:
    mapped = sector_for_symbol(ticker)
    return mapped[0] if mapped else "unknown"


def evaluate_portfolio_overlay(
    candidate: "ManeuverCandidate",
    batch_selected: list["ManeuverCandidate"],
    portfolio_state: "PortfolioState | None" = None,
) -> PortfolioOverlayResult:
    """
    Check whether adding this candidate would concentrate sector/factor risk.

    Returns warnings for display — does not block the maneuver.
    """
    result = PortfolioOverlayResult(sector=_sector(candidate.ticker))
    warnings: list[str] = []

    same_sector = sum(1 for c in batch_selected if _sector(c.ticker) == result.sector)
    result.sector_count_after_add = same_sector + 1
    if result.sector_count_after_add > SECTOR_CONCENTRATION_LIMIT:
        warnings.append(
            f"Сектор «{result.sector}» уже представлен {same_sector} манёврами — "
            f"добавление усилит концентрацию."
        )

    vec = _factor_vector(candidate)
    max_overlap = 0.0
    overlap_ticker = ""
    for existing in batch_selected:
        overlap = cosine_similarity(vec, _factor_vector(existing))
        if overlap > max_overlap:
            max_overlap = overlap
            overlap_ticker = existing.ticker
    result.max_factor_overlap = round(max_overlap, 4)

    if max_overlap >= FACTOR_OVERLAP_WARN and overlap_ticker:
        warnings.append(
            f"Факторный профиль близок к {overlap_ticker} "
            f"(cosine={max_overlap:.2f}) — возможна скрытая корреляция."
        )

    if portfolio_state and portfolio_state.open_positions >= 6:
        warnings.append(
            f"В портфеле уже {portfolio_state.open_positions} открытых позиций — "
            "суммарная экспозиция может быть высокой."
        )

    result.warnings = warnings
    return result
