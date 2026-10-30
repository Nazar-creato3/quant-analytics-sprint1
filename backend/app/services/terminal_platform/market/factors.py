"""Explanatory quant factors for Terminal Quant / Market context strip."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.services.terminal_platform.market.schemas import (
    MarketPulseBlock,
    PortfolioSummaryBlock,
    QuantFactorRow,
)


def build_quant_factors(
    *,
    pulse: Optional[MarketPulseBlock] = None,
    portfolio: Optional[PortfolioSummaryBlock] = None,
    index_change_pcts: Optional[dict[str, Optional[float]]] = None,
) -> list[QuantFactorRow]:
    """
    Produce human-readable factor cards from live Terminal inputs.
    Weights sum ≈ 1.0 across included factors (renormalized).
    """
    now = datetime.now(timezone.utc).isoformat()
    index_change_pcts = index_change_pcts or {}
    raw: list[QuantFactorRow] = []

    vix = None
    if pulse:
        for g in pulse.global_snapshot:
            if g.key == "VIX" and g.status == "ok" and g.price is not None:
                vix = g.price
                break
        if pulse.fear_greed is not None:
            # Map F&G to contribution around neutral 50
            contrib = (pulse.fear_greed - 50) / 50.0
            raw.append(
                QuantFactorRow(
                    name="Sentiment (Fear & Greed)",
                    weight=0.30,
                    contribution=round(contrib, 4),
                    source="terminal.pulse",
                    freshness=now,
                    confidence=0.7 if pulse.fear_greed_components else 0.4,
                    why=(
                        f"Composite score {pulse.fear_greed} ({pulse.label or 'n/a'}) "
                        "from VIX / breadth / momentum — positive contribution = greed bias."
                    ),
                )
            )
        if pulse.volatility_regime and pulse.volatility_regime != "unknown":
            regime_map = {"calm": -0.2, "moderate": 0.0, "elevated": 0.35, "extreme": 0.7}
            raw.append(
                QuantFactorRow(
                    name="Volatility regime",
                    weight=0.25,
                    contribution=regime_map.get(pulse.volatility_regime, 0.0),
                    source="terminal.pulse.vix",
                    freshness=now,
                    confidence=0.8 if vix is not None else 0.3,
                    why=(
                        f"Regime '{pulse.volatility_regime}'"
                        + (f" from VIX={vix:.2f}" if vix is not None else "")
                        + ". Elevated/extreme regimes raise risk contribution."
                    ),
                )
            )

    spx = index_change_pcts.get("SPX")
    if spx is not None:
        raw.append(
            QuantFactorRow(
                name="Equity beta (SPX day)",
                weight=0.20,
                contribution=round(float(spx) / 100.0, 4),
                source="terminal.indices",
                freshness=now,
                confidence=0.75,
                why=f"S&P 500 daily change {spx:+.2f}% used as a market-beta proxy for the session.",
            )
        )

    if portfolio and portfolio.has_positions:
        exp = float(portfolio.exposure_pct or 0)
        raw.append(
            QuantFactorRow(
                name="Portfolio exposure",
                weight=0.25,
                contribution=round(exp / 100.0, 4),
                source="portfolio.metrics",
                freshness=portfolio.as_of or now,
                confidence=0.85,
                why=(
                    f"Deployed exposure {exp:.1f}% of capital "
                    f"({portfolio.open_positions} open positions). "
                    "Higher exposure amplifies market moves in portfolio PnL."
                ),
            )
        )
        if portfolio.concentration_pct is not None:
            raw.append(
                QuantFactorRow(
                    name="Concentration",
                    weight=0.15,
                    contribution=round(float(portfolio.concentration_pct) / 100.0, 4),
                    source="portfolio.positions",
                    freshness=portfolio.as_of or now,
                    confidence=0.7,
                    why=(
                        f"Largest position is {portfolio.concentration_pct:.1f}% of book — "
                        "idiosyncratic risk rises with concentration."
                    ),
                )
            )
    # GA16-314: without a portfolio do not invent a weight-0.15 exposure factor.

    # Renormalize weights
    total_w = sum(f.weight or 0 for f in raw) or 1.0
    out: list[QuantFactorRow] = []
    for f in raw:
        w = (f.weight or 0) / total_w
        out.append(f.model_copy(update={"weight": round(w, 4)}))
    return out
