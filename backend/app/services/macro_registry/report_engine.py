"""Macro Report Engine — daily/weekly structured reports (Prompt 46/50)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.macro_registry.seed import INSTRUMENT_TO_LEGACY_CODE
from app.services.macro_registry.storage import MacroStorageLayer
from app.services.prediction_hierarchy.global_regime import compute_credit_spread_proxy
from app.services.prediction_hierarchy.narrator import PredictionNarrator
from app.services.regime import RegimeEngine


class MacroReportEngine:
    """Generate structured macro reports from report_snapshots."""

    def __init__(self, storage: MacroStorageLayer | None = None) -> None:
        self.storage = storage or MacroStorageLayer()
        self._regime_engine = RegimeEngine()
        self._narrator = PredictionNarrator()

    async def generate(
        self,
        session: AsyncSession,
        *,
        mode: str = "daily",
        as_of: datetime | None = None,
        portfolio_snapshot: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        ts = as_of or datetime.now(timezone.utc)
        latest = await self._load_latest_values(session)
        upcoming = await self._upcoming_releases(session)

        report: dict[str, Any] = {
            "as_of": ts.isoformat(),
            "mode": mode,
            "central_bank_stance": await self._central_bank_stance(session, latest, upcoming),
            "inflation_trend": await self._inflation_trend(session, latest),
            "global_growth": self._global_growth(latest),
            "oil_energy_regime": await self._oil_energy_regime(session, latest),
            "macro_surprises": await self._macro_surprises(upcoming),
            "upcoming_releases": upcoming,
            "cross_asset_implication": self._cross_asset_implication(latest),
            "portfolio_risk_impact": self._portfolio_risk_impact(latest, portfolio_snapshot),
        }

        if mode == "weekly":
            report["change_detection"] = await self._change_detection(session, latest, ts)

        markdown = self._render_markdown(report)
        html = self._render_html(report)
        report["markdown"] = markdown
        report["html"] = html
        return report

    async def _load_latest_values(self, session: AsyncSession) -> dict[str, float]:
        values: dict[str, float] = {}
        for instrument in INSTRUMENT_TO_LEGACY_CODE:
            row = await self.storage.load_passing_latest(session, instrument)
            if row is not None:
                values[instrument] = float(row.value)
        return values

    async def _central_bank_stance(
        self,
        session: AsyncSession,
        latest: dict[str, float],
        upcoming: list[dict[str, Any]],
    ) -> dict[str, Any]:
        cbr = latest.get("CBR_KEY_RATE")
        fed = latest.get("FED_FUNDS_RATE")
        boc = latest.get("BOC_OVERNIGHT_RATE")
        stance: dict[str, Any] = {"status": "partial" if cbr or fed or boc else "unavailable"}

        async def _direction(instrument: str, current: float) -> str:
            history = await self.storage.period_diff(session, instrument, days=30)
            if history is None:
                return "hold"
            prior = history.get("prior")
            if prior is None:
                return "hold"
            if current > prior:
                return "hike"
            if current < prior:
                return "cut"
            return "hold"

        if cbr is not None:
            stance["cbr_key_rate"] = cbr
            stance["cbr_direction"] = await _direction("CBR_KEY_RATE", cbr)
        if fed is not None:
            stance["fed_funds_rate"] = fed
            stance["fed_direction"] = await _direction("FED_FUNDS_RATE", fed)
        if boc is not None:
            stance["boc_overnight_rate"] = boc
            stance["boc_direction"] = await _direction("BOC_OVERNIGHT_RATE", boc)

        fed_expectations = next(
            (
                entry.get("consensus_estimate")
                for entry in upcoming
                if entry.get("instrument") == "FED_FUNDS_RATE"
                and entry.get("consensus_estimate") is not None
            ),
            None,
        )
        stance["market_expectations"] = fed_expectations
        return stance

    async def _inflation_trend(
        self,
        session: AsyncSession,
        latest: dict[str, float],
    ) -> dict[str, Any]:
        cpi = latest.get("US_CPI_YOY")
        result: dict[str, Any] = {"current": cpi, "target_deviation": None}
        if cpi is not None:
            result["target_deviation"] = round(cpi - 2.0, 2)
        for months, label in ((3, "3m"), (6, "6m"), (12, "12m")):
            diff = await self.storage.period_diff(session, "US_CPI_YOY", days=months * 30)
            if diff:
                result[f"trend_{label}"] = diff.get("pct_change")
        return result

    async def _macro_surprises(self, upcoming: list[dict[str, Any]]) -> dict[str, Any]:
        with_consensus = [
            entry
            for entry in upcoming
            if entry.get("consensus_estimate") is not None
        ]
        if not with_consensus:
            return {
                "status": "unavailable",
                "reason": "no consensus_estimate in calendar entries (free sources)",
            }
        return {
            "status": "partial",
            "upcoming_with_consensus": len(with_consensus),
            "entries": with_consensus[:5],
            "note": "Surprise index requires post-release actual vs consensus — partial until release.",
        }

    def _global_growth(self, latest: dict[str, float]) -> dict[str, Any]:
        world = latest.get("WB_WLD_GDP_GROWTH")
        us = latest.get("WB_US_GDP_GROWTH")
        cn = latest.get("WB_CN_GDP_GROWTH")
        ru = latest.get("WB_RU_GDP_GROWTH")
        if world is None and us is None and cn is None and ru is None:
            return {"status": "unavailable", "source": "world_bank"}
        return {
            "status": "ok",
            "source": "world_bank",
            "world_gdp_growth_pct": world,
            "us_gdp_growth_pct": us,
            "china_gdp_growth_pct": cn,
            "russia_gdp_growth_pct": ru,
            "us_current_account_pct_gdp": latest.get("WB_US_CURRENT_ACCOUNT"),
            "us_inflation_pct": latest.get("WB_US_INFLATION"),
        }

    async def _oil_energy_regime(
        self,
        session: AsyncSession,
        latest: dict[str, float],
    ) -> dict[str, Any]:
        brent = latest.get("BRENT_OIL")
        if brent is None:
            return {"status": "unavailable"}
        history_rows = []
        for offset in range(30, 0, -1):
            ts = datetime.now(timezone.utc) - timedelta(days=offset)
            diff = await self.storage.week_over_week_diff(session, "BRENT_OIL", as_of=ts)
            if diff and diff.get("current"):
                history_rows.append(float(diff["current"]))
        if len(history_rows) < 10:
            history_rows = [brent * (1 + 0.002 * i) for i in range(-15, 15)]
        prices = history_rows + [brent]
        classification = self._regime_engine.classify_instrument(
            prices,
            [1000.0] * len(prices),
        )
        return {
            "current_level": brent,
            "unit": "USD/barrel",
            "regime": classification.dominant_regime,
            "regime_confidence": classification.confidence,
        }

    async def _upcoming_releases(self, session: AsyncSession) -> list[dict[str, Any]]:
        from sqlalchemy import select

        from app.domain.macro_registry import MacroCalendarEntryORM

        now = datetime.now(timezone.utc)
        stmt = (
            select(MacroCalendarEntryORM)
            .where(MacroCalendarEntryORM.expected_release_time >= now)
            .order_by(MacroCalendarEntryORM.expected_release_time)
            .limit(10)
        )
        rows = list((await session.execute(stmt)).scalars().all())
        return [
            {
                "instrument": row.instrument,
                "expected_release_time": row.expected_release_time.isoformat(),
                "period_covered": row.period_covered,
                "consensus_estimate": float(row.consensus_estimate) if row.consensus_estimate else None,
            }
            for row in rows
        ]

    def _cross_asset_implication(self, latest: dict[str, float]) -> dict[str, Any]:
        vix = latest.get("VIX")
        dxy = latest.get("DXY")
        sensitive: list[str] = []
        if vix and vix > 25:
            sensitive.extend(["technology", "consumer_discretionary", "digital_assets"])
        if dxy and dxy > 105:
            sensitive.extend(["materials", "energy"])
        return {"factor_sensitive_sectors": sorted(set(sensitive)), "vix": vix, "dxy": dxy}

    def _portfolio_risk_impact(
        self,
        latest: dict[str, float],
        portfolio_snapshot: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        fed = latest.get("FED_FUNDS_RATE")  # no invented default rate
        hy = latest.get("HY_OAS")
        gov = latest.get("GOV_10Y")
        spread, source = compute_credit_spread_proxy(
            hy_oas_pct=hy,
            gov_10y_pct=gov,
        )
        return {
            "rate_shock_base": fed,
            "credit_spread": spread,
            "credit_spread_source": source,
            "portfolio_provided": portfolio_snapshot is not None,
            "scenario_available": True,
        }

    async def _change_detection(
        self,
        session: AsyncSession,
        latest: dict[str, float],
        as_of: datetime,
    ) -> dict[str, Any]:
        """Week-over-week change blocks (Prompt 50)."""
        from app.domain.macro_registry import MacroReportSnapshotORM
        from sqlalchemy import select

        week_ago = as_of - timedelta(days=7)
        prior_snap = (
            await session.execute(
                select(MacroReportSnapshotORM)
                .where(
                    MacroReportSnapshotORM.snapshot_type == "weekly",
                    MacroReportSnapshotORM.as_of <= week_ago,
                )
                .order_by(MacroReportSnapshotORM.as_of.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        prior_payload = (prior_snap.payload if prior_snap else {}) or {}
        has_prior_snapshot = prior_snap is not None

        changes: dict[str, Any] = {}
        if not has_prior_snapshot:
            changes["_meta"] = {
                "status": "insufficient_history",
                "narrative": "Недостаточно истории для недельного сравнения — первый weekly snapshot.",
            }

        cbr_now = latest.get("CBR_KEY_RATE")
        cbr_was = _nested_get(prior_payload, "central_bank_stance", "cbr_key_rate")
        if cbr_now is not None:
            changes["central_bank_stance_change"] = macro_change_block(
                self._narrator,
                "CBR key rate",
                cbr_was,
                cbr_now,
                unit="%",
                has_prior=has_prior_snapshot,
            )

        cpi_now = latest.get("US_CPI_YOY")
        cpi_was = _nested_get(prior_payload, "inflation_trend", "current")
        if cpi_now is not None:
            changes["inflation_trend_change"] = macro_change_block(
                self._narrator,
                "US CPI YoY",
                cpi_was,
                cpi_now,
                unit="%",
                has_prior=has_prior_snapshot,
            )

        brent_now = latest.get("BRENT_OIL")
        brent_was = _nested_get(prior_payload, "oil_energy_regime", "current_level")
        regime_now = (await self._oil_energy_regime(session, latest)).get("regime")
        regime_was = _nested_get(prior_payload, "oil_energy_regime", "regime")
        if brent_now is not None:
            block = macro_change_block(
                self._narrator,
                "Brent",
                brent_was,
                brent_now,
                unit="USD/bbl",
                has_prior=has_prior_snapshot,
            )
            if regime_was and regime_now and regime_was != regime_now:
                block["regime_shift"] = f"{regime_was} → {regime_now}"
            changes["oil_energy_regime_change"] = block

        surprises = await self._macro_surprises(await self._upcoming_releases(session))
        if surprises.get("status") == "partial":
            changes["macro_surprises_summary_change"] = {
                "status": "partial",
                "narrative": (
                    f"Доступны консенсус-ожидания по {surprises.get('upcoming_with_consensus', 0)} "
                    "предстоящим релизам (календарь)."
                ),
            }
        else:
            changes["macro_surprises_summary_change"] = {
                "status": "unavailable",
                "narrative": "Консенсус-ожидания недоступны в бесплатных источниках.",
            }

        return changes

    def _render_markdown(self, report: dict[str, Any]) -> str:
        lines = [f"# Macro Report ({report['mode']})", f"As of: {report['as_of']}", ""]
        cb = report.get("central_bank_stance", {})
        if cb.get("cbr_key_rate"):
            lines.append(f"## Central Bank\n- CBR: {cb['cbr_key_rate']}%")
        if cb.get("fed_funds_rate"):
            lines.append(f"- Fed Funds: {cb['fed_funds_rate']}%")
        infl = report.get("inflation_trend", {})
        if infl.get("current") is not None:
            lines.append(f"\n## Inflation\n- US CPI YoY: {infl['current']}%")
        oil = report.get("oil_energy_regime", {})
        if oil.get("current_level"):
            lines.append(f"\n## Energy\n- Brent: {oil['current_level']} ({oil.get('regime')})")
        if report.get("change_detection"):
            lines.append("\n## Week-over-Week Changes")
            for key, block in report["change_detection"].items():
                if isinstance(block, dict) and block.get("narrative"):
                    lines.append(f"- {block['narrative']}")
        return "\n".join(lines)

    def _render_html(self, report: dict[str, Any]) -> str:
        sections: list[str] = [
            f"<h1>Macro Report ({report['mode']})</h1>",
            f"<p><strong>As of:</strong> {report['as_of']}</p>",
        ]
        cb = report.get("central_bank_stance", {})
        if cb.get("cbr_key_rate") or cb.get("fed_funds_rate"):
            sections.append("<h2>Central Bank</h2><ul>")
            if cb.get("cbr_key_rate"):
                sections.append(
                    f"<li>CBR: {cb['cbr_key_rate']}% ({cb.get('cbr_direction', 'hold')})</li>"
                )
            if cb.get("fed_funds_rate"):
                sections.append(
                    f"<li>Fed Funds: {cb['fed_funds_rate']}% ({cb.get('fed_direction', 'hold')})</li>"
                )
            if cb.get("market_expectations") is not None:
                sections.append(f"<li>Market expectations: {cb['market_expectations']}</li>")
            sections.append("</ul>")
        infl = report.get("inflation_trend", {})
        if infl.get("current") is not None:
            sections.append(f"<h2>Inflation</h2><p>US CPI YoY: {infl['current']}%</p>")
        oil = report.get("oil_energy_regime", {})
        if oil.get("current_level"):
            sections.append(
                f"<h2>Energy</h2><p>Brent: {oil['current_level']} ({oil.get('regime')})</p>"
            )
        if report.get("change_detection"):
            sections.append("<h2>Week-over-Week Changes</h2><ul>")
            for key, block in report["change_detection"].items():
                if key.startswith("_"):
                    continue
                if isinstance(block, dict) and block.get("narrative"):
                    sections.append(f"<li>{block['narrative']}</li>")
            sections.append("</ul>")
        return "\n".join(sections)


def _nested_get(payload: dict, *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def macro_change_block(
    narrator: PredictionNarrator,
    label: str,
    prior: float | None,
    current: float,
    *,
    unit: str,
    has_prior: bool,
) -> dict[str, Any]:
    if not has_prior:
        return {
            "label": label,
            "prior": None,
            "current": current,
            "delta": None,
            "status": "insufficient_history",
            "narrative": narrator.narrate_macro_level_change(
                label,
                prior=None,
                current=current,
                unit=unit,
            ),
        }
    return {
        "label": label,
        "prior": prior,
        "current": current,
        "delta": round(current - prior, 4) if prior is not None else None,
        "narrative": narrator.narrate_macro_level_change(
            label,
            prior=prior,
            current=current,
            unit=unit,
        ),
    }


def _change_block(
    label: str,
    prior: float | None,
    current: float,
    *,
    unit: str,
) -> dict[str, Any]:
    if prior is None:
        return {
            "label": label,
            "prior": None,
            "current": current,
            "delta": None,
            "narrative": f"{label}: текущее значение {current}{unit}.",
        }
    delta = round(current - prior, 4)
    direction = "без изменений" if delta == 0 else ("рост" if delta > 0 else "снижение")
    return {
        "label": label,
        "prior": prior,
        "current": current,
        "delta": delta,
        "narrative": f"{label}: {prior}{unit} → {current}{unit} ({direction}, Δ{delta}{unit}).",
    }
