"""Tests for Macro Registry system (Prompts 41-50)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.macro_registry.adapters.base import build_raw_response, compute_payload_hash
from app.services.macro_registry.adapters.central_bank import CentralBankAdapter
from app.services.macro_registry.adapters.calendar import MacroCalendarAdapter
from app.services.macro_registry.adapters.energy import EnergyAdapter
from app.services.macro_registry.fred_client import parse_fred_endpoint, resolve_fred_api_key
from app.services.macro_registry.normalization import NormalizationLayer
from app.services.macro_registry.quality_gate import QualityGate, cron_to_refresh_hours, infer_refresh_hours
from app.services.macro_registry.report_engine import MacroReportEngine, _change_block
from app.services.macro_registry.seed import MACRO_SOURCE_SEED, INSTRUMENT_TO_LEGACY_CODE
from app.services.macro_registry.transformers import transform_fred_cpi_yoy
from app.services.macro_registry.types import InternalObservation, MacroSourceConfig, NormalizedObservation

FIXTURES = Path(__file__).parent / "fixtures" / "macro"


def _config(source_id: str, category: str, symbol: str, endpoint: str, transformer: str) -> MacroSourceConfig:
    return MacroSourceConfig(
        source_id=source_id,
        category=category,
        symbol=symbol,
        endpoint=endpoint,
        refresh_interval="0 8 * * *",
        priority=10,
        is_free=True,
        fallback_source=None,
        transformer=transformer,
    )


class TestTransformers:
    def test_cpi_yoy_from_real_shaped_index(self):
        payload = json.loads((FIXTURES / "fred_cpi_sample.json").read_text(encoding="utf-8"))
        observations = []
        for obs in payload["observations"]:
            dt = datetime.strptime(obs["date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            observations.append(
                InternalObservation(
                    instrument="US_CPI_YOY",
                    value=float(obs["value"]),
                    currency=None,
                    unit="index",
                    release_time=dt,
                    observation_time=dt,
                    period=dt.strftime("%Y-%m"),
                )
            )
        normalized = transform_fred_cpi_yoy(
            observations,
            source_id="fred_cpi",
            raw_payload_hash="abc123",
        )
        assert normalized
        latest = normalized[-1]
        assert latest.unit == "%"
        assert 0.0 < latest.value < 15.0

    def test_confidence_lower_for_revision_zero(self):
        obs = InternalObservation(
            instrument="VIX",
            value=18.5,
            currency=None,
            unit="index_points",
            release_time=datetime.now(timezone.utc),
            observation_time=datetime.now(timezone.utc),
            period="2025-06",
            revision=0,
        )
        from app.services.macro_registry.transformers import transform_fred_level

        n0 = transform_fred_level(obs, source_id="fred_vix", raw_payload_hash="h1")
        obs2 = InternalObservation(
            instrument="VIX",
            value=18.5,
            currency=None,
            unit="index_points",
            release_time=datetime.now(timezone.utc),
            observation_time=datetime.now(timezone.utc),
            period="2025-06",
            revision=2,
        )
        n2 = transform_fred_level(obs2, source_id="fred_vix", raw_payload_hash="h2")
        assert n0.confidence < n2.confidence


class TestAdapters:
    def test_central_bank_normalize_cbr_xml(self):
        xml = (FIXTURES / "cbr_key_rate_sample.xml").read_text(encoding="utf-8")
        config = _config("cbr_key_rate", "rate", "CBR_KEY_RATE", "adapter:cbr_soap", "transform_cbr_key_rate")
        adapter = CentralBankAdapter(config)
        raw = build_raw_response(config, xml, content_type="text/xml")
        rows = adapter.normalize(raw)
        assert len(rows) == 2
        assert rows[-1].value == 18.0
        assert rows[-1].currency == "RUB"

    def test_energy_normalize_fred_brent(self):
        payload = (FIXTURES / "fred_brent_sample.json").read_text(encoding="utf-8")
        config = _config("fred_brent", "energy", "BRENT_OIL", "adapter:fred:DCOILBRENTEU", "transform_fred_level")
        adapter = EnergyAdapter(config)
        raw = build_raw_response(config, payload)
        rows = adapter.normalize(raw)
        assert rows[-1].value == pytest.approx(75.0)
        assert rows[-1].unit == "USD/barrel"

    @pytest.mark.asyncio
    async def test_fallback_on_primary_failure(self):
        config = _config("fred_brent", "energy", "BRENT_OIL", "adapter:fred:DCOILBRENTEU", "transform_fred_level")
        adapter = EnergyAdapter(config)

        async def fail_fetch(client):
            raise ConnectionError("primary down")

        with patch.object(adapter, "fetch", side_effect=fail_fetch):
            with pytest.raises(ConnectionError):
                await adapter.fetch_with_retry()

    def test_calendar_adapter_entries(self):
        config = _config("fomc_calendar", "calendar", "FOMC_SCHEDULE", "adapter:fomc_calendar", "transform_calendar")
        adapter = MacroCalendarAdapter(config)
        import asyncio

        raw = asyncio.get_event_loop().run_until_complete(adapter.fetch(MagicMock()))
        entries = adapter.parse_calendar(raw)
        assert entries
        assert entries[0].instrument == "FED_FUNDS_RATE"
        assert entries[0].consensus_estimate is None


class TestQualityGate:
    def test_future_timestamp_fails(self):
        gate = QualityGate()
        future = datetime.now(timezone.utc) + timedelta(days=2)
        obs = NormalizedObservation(
            instrument="VIX",
            source_id="fred_vix",
            value=20.0,
            currency=None,
            unit="index_points",
            release_time=future,
            observation_time=future,
            period="2025-07",
            revision=0,
            confidence=0.8,
            raw_payload_hash="hash",
        )
        assert gate.evaluate_one(obs) == "missing"

    def test_suspect_outlier_preserved_not_passing(self):
        gate = QualityGate()
        now = datetime.now(timezone.utc)
        obs = NormalizedObservation(
            instrument="VIX",
            source_id="fred_vix",
            value=80.0,
            currency=None,
            unit="index_points",
            release_time=now,
            observation_time=now,
            period="2025-07",
            revision=0,
            confidence=0.8,
            raw_payload_hash="hash",
        )
        flag = gate.evaluate_one(obs, prior_values=[18.0, 19.0, 17.5, 18.2, 19.1])
        assert flag == "suspect"
        assert not gate.is_passing(flag)

    def test_stale_source(self):
        gate = QualityGate()
        old = datetime.now(timezone.utc) - timedelta(days=10)
        obs = NormalizedObservation(
            instrument="VIX",
            source_id="fred_vix",
            value=20.0,
            currency=None,
            unit="index_points",
            release_time=old,
            observation_time=old,
            period=old.strftime("%Y-%m-%d"),
            revision=0,
            confidence=0.8,
            raw_payload_hash="hash",
        )
        assert gate.evaluate_one(obs, refresh_interval_hours=24.0) == "stale"

    def test_monthly_latest_passes_within_cadence(self):
        gate = QualityGate()
        now = datetime.now(timezone.utc)
        obs_time = now - timedelta(days=40)
        obs = NormalizedObservation(
            instrument="US_CPI_YOY",
            source_id="fred_cpi",
            value=3.2,
            currency=None,
            unit="%",
            release_time=obs_time,
            observation_time=obs_time,
            period=obs_time.strftime("%Y-%m"),
            revision=0,
            confidence=0.8,
            raw_payload_hash="hash",
        )
        flag = gate.evaluate_one(
            obs,
            refresh_interval_hours=cron_to_refresh_hours("0 10 15 * *"),
            now=now,
            is_latest=True,
        )
        assert flag == "ok"

    def test_historical_rows_do_not_block_latest(self):
        gate = QualityGate()
        now = datetime.now(timezone.utc)
        historical = datetime(now.year - 1, 6, 1, tzinfo=timezone.utc)
        latest_time = now - timedelta(days=2)
        historical_obs = NormalizedObservation(
            instrument="VIX",
            source_id="fred_vix",
            value=18.0,
            currency=None,
            unit="index_points",
            release_time=historical,
            observation_time=historical,
            period=historical.strftime("%Y-%m-%d"),
            revision=0,
            confidence=0.8,
            raw_payload_hash="hash",
        )
        latest_obs = NormalizedObservation(
            instrument="VIX",
            source_id="fred_vix",
            value=20.0,
            currency=None,
            unit="index_points",
            release_time=latest_time,
            observation_time=latest_time,
            period=latest_time.strftime("%Y-%m-%d"),
            revision=0,
            confidence=0.8,
            raw_payload_hash="hash",
        )
        flags = gate.evaluate_batch(
            [historical_obs, latest_obs],
            refresh_interval_hours=24.0,
            now=now,
        )
        assert flags[(historical_obs.instrument, historical_obs.observation_time)] == "ok"
        assert flags[(latest_obs.instrument, latest_obs.observation_time)] == "ok"

    def test_infer_refresh_hours_from_period(self):
        assert infer_refresh_hours("2025-07-19") == 24.0
        assert infer_refresh_hours("2025-07", refresh_interval_hours=24.0 * 35) == 24.0 * 35
        assert infer_refresh_hours("2025-07", refresh_interval_hours=24.0) == 24.0 * 35
        assert infer_refresh_hours("2026-Q1") == 24.0 * 92
        assert infer_refresh_hours("2025") == 24.0 * 365

    def test_quarterly_latest_passes_within_cadence(self):
        gate = QualityGate()
        now = datetime.now(timezone.utc)
        obs_time = datetime(2026, 3, 1, tzinfo=timezone.utc)
        obs = NormalizedObservation(
            instrument="EU_GDP_YOY_Q",
            source_id="eu_gdp_yoy_q",
            value=1.2,
            currency=None,
            unit="%",
            release_time=obs_time,
            observation_time=obs_time,
            period="2026-Q1",
            revision=0,
            confidence=0.8,
            raw_payload_hash="hash",
        )
        flag = gate.evaluate_one(
            obs,
            refresh_interval_hours=cron_to_refresh_hours("0 7 1 * *"),
            now=now,
            is_latest=True,
        )
        assert flag == "ok"

    def test_annual_latest_passes_within_cadence(self):
        gate = QualityGate()
        now = datetime.now(timezone.utc)
        obs_time = datetime(2025, 12, 31, tzinfo=timezone.utc)
        obs = NormalizedObservation(
            instrument="EU_GDP_GROWTH",
            source_id="eu_gdp_growth",
            value=1.5,
            currency=None,
            unit="%",
            release_time=obs_time,
            observation_time=obs_time,
            period="2025",
            revision=0,
            confidence=0.8,
            raw_payload_hash="hash",
        )
        flag = gate.evaluate_one(
            obs,
            refresh_interval_hours=cron_to_refresh_hours("0 7 1 * *"),
            now=now,
            is_latest=True,
        )
        assert flag == "ok"


class TestDeduplication:
    def test_payload_hash_dedup(self):
        payload = '{"value": 21.0}'
        h1 = compute_payload_hash(payload)
        h2 = compute_payload_hash(payload)
        assert h1 == h2
        assert h1 != compute_payload_hash('{"value": 21.1}')


class TestReliabilityScore:
    def test_update_reliability_score_decay(self):
        from app.services.macro_registry.reliability import update_reliability_score

        high = update_reliability_score(1.0, passed=True)
        low = update_reliability_score(1.0, passed=False)
        assert high > low
        assert 0.0 <= low <= 1.0

    def test_adjust_confidence_for_reliability(self):
        from app.services.macro_registry.reliability import adjust_confidence_for_reliability

        assert adjust_confidence_for_reliability(0.8, 0.5) < 0.8


class TestStorageCompaction:
    @pytest.mark.asyncio
    async def test_compact_raw_responses_respects_retention(self):
        from datetime import datetime, timedelta, timezone

        from app.services.macro_registry.storage import MacroStorageLayer

        storage = MacroStorageLayer()
        session = AsyncMock()
        old_row = MagicMock()
        session.execute = AsyncMock(
            side_effect=[
                MagicMock(first=lambda: (1,)),
                MagicMock(rowcount=2),
                MagicMock(all=lambda: [(1,), (2,)]),
            ]
        )
        session.commit = AsyncMock()
        result = await storage.compact_raw_responses(session, retention_years=2)
        assert "deleted" in result
        assert result["retained"] == 2


class TestReportEngine:
    def test_change_block_narrative(self):
        block = _change_block("CBR key rate", 21.0, 18.0, unit="%")
        assert block["delta"] == -3.0
        assert "21.0%" in block["narrative"]
        assert "18.0%" in block["narrative"]

    def test_macro_change_block_uses_narrator(self):
        from app.services.macro_registry.report_engine import macro_change_block
        from app.services.prediction_hierarchy.narrator import PredictionNarrator

        narrator = PredictionNarrator()
        block = macro_change_block(
            narrator,
            "US CPI YoY",
            3.0,
            3.2,
            unit="%",
            has_prior=True,
        )
        assert "3.0" in block["narrative"]
        assert block["delta"] == pytest.approx(0.2)

    def test_macro_change_block_insufficient_history(self):
        from app.services.macro_registry.report_engine import macro_change_block
        from app.services.prediction_hierarchy.narrator import PredictionNarrator

        block = macro_change_block(
            PredictionNarrator(),
            "Brent",
            None,
            75.0,
            unit="USD/bbl",
            has_prior=False,
        )
        assert block["status"] == "insufficient_history"

    def test_inflation_trend_horizons_differ(self):
        from app.services.macro_registry.report_engine import MacroReportEngine

        engine = MacroReportEngine()
        diffs = {
            90: {"pct_change": 0.1},
            180: {"pct_change": 0.3},
            360: {"pct_change": 0.6},
        }

        async def fake_period_diff(_session, _instrument, *, days, as_of=None):
            return diffs.get(days)

        engine.storage.period_diff = fake_period_diff
        import asyncio

        result = asyncio.get_event_loop().run_until_complete(
            engine._inflation_trend(AsyncMock(), {"US_CPI_YOY": 3.2})
        )
        assert result["trend_3m"] == 0.1
        assert result["trend_6m"] == 0.3
        assert result["trend_12m"] == 0.6

    def test_html_renderer_present(self):
        from app.services.macro_registry.report_engine import MacroReportEngine

        engine = MacroReportEngine()
        html = engine._render_html(
            {
                "mode": "daily",
                "as_of": "2026-07-22T00:00:00+00:00",
                "central_bank_stance": {"fed_funds_rate": 5.25, "fed_direction": "hold"},
                "inflation_trend": {"current": 3.2},
                "oil_energy_regime": {"current_level": 75.0, "regime": "trend_up"},
            }
        )
        assert "<h1>" in html
        assert "Fed Funds" in html

    @pytest.mark.asyncio
    async def test_weekly_change_detection(self):
        engine = MacroReportEngine()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))
        engine.storage.load_passing_latest = AsyncMock(
            side_effect=lambda _s, instrument: (
                MagicMock(value={"CBR_KEY_RATE": 18.0, "US_CPI_YOY": 3.2, "BRENT_OIL": 75.0}[instrument])
                if instrument in {"CBR_KEY_RATE", "US_CPI_YOY", "BRENT_OIL"}
                else None
            )
        )
        engine.storage.week_over_week_diff = AsyncMock(return_value={"pct_change": 0.5})
        engine._oil_energy_regime = AsyncMock(return_value={"current_level": 75.0, "regime": "trend_up"})
        report = await engine.generate(session, mode="weekly")
        assert "change_detection" in report
        assert "central_bank_stance_change" in report["change_detection"]


class TestNormalizationRevisions:
    @pytest.mark.asyncio
    async def test_new_revision_without_overwrite(self):
        layer = NormalizationLayer()
        session = AsyncMock()
        existing = MagicMock(revision=0, value=21.0)
        session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=lambda: existing)
        )
        session.add = MagicMock()
        session.flush = AsyncMock()
        now = datetime.now(timezone.utc)
        obs = NormalizedObservation(
            instrument="CBR_KEY_RATE",
            source_id="cbr_key_rate",
            value=18.0,
            currency="RUB",
            unit="%",
            release_time=now,
            observation_time=now,
            period="2025-07",
            revision=0,
            confidence=0.8,
            raw_payload_hash="hash",
        )
        stored = await layer.persist_observations(session, raw_response_id=1, observations=[obs])
        assert stored == 1
        added = session.add.call_args[0][0]
        assert added.revision == 1


class TestCanadaSources:
    def test_canada_sources_registered_in_seed(self):
        source_ids = {row["source_id"] for row in MACRO_SOURCE_SEED}
        assert "boc_overnight_rate" in source_ids
        assert "fred_ca_cpi" in source_ids
        assert "fred_ca_unemployment" in source_ids
        assert "fred_ca_usdcad" in source_ids

    def test_fred_ca_cpi_uses_level_transformer(self):
        by_id = {row["source_id"]: row for row in MACRO_SOURCE_SEED}
        assert by_id["fred_ca_cpi"]["transformer"] == "transform_fred_level"

    def test_canada_legacy_code_mapping(self):
        assert INSTRUMENT_TO_LEGACY_CODE["BOC_OVERNIGHT_RATE"] == "rate_cb_ca"
        assert INSTRUMENT_TO_LEGACY_CODE["CA_CPI_YOY"] == "cpi_ca"
        assert INSTRUMENT_TO_LEGACY_CODE["USDCAD"] == "usdcad"

    def test_fred_endpoint_routing(self):
        assert parse_fred_endpoint("adapter:fred:DGS10") == ("us", "DGS10")
        assert parse_fred_endpoint("adapter:fred_ca:DEXCAUS") == ("canada", "DEXCAUS")
        assert parse_fred_endpoint("adapter:cbr_soap") is None

    def test_fred_api_key_routing(self):
        with patch("app.services.macro_registry.fred_client.settings") as mock_settings:
            mock_settings.FRED_API_KEY = "us-key"
            mock_settings.FRED_CANADA_API_KEY = "ca-key"
            assert resolve_fred_api_key("us") == "us-key"
            assert resolve_fred_api_key("canada") == "ca-key"

    def test_boc_valet_normalize(self):
        payload = (FIXTURES / "boc_overnight_sample.json").read_text(encoding="utf-8")
        config = _config(
            "boc_overnight_rate",
            "rate",
            "BOC_OVERNIGHT_RATE",
            "adapter:boc_valet:V39079",
            "transform_boc_key_rate",
        )
        adapter = CentralBankAdapter(config)
        raw = build_raw_response(config, payload)
        rows = adapter.normalize(raw)
        assert len(rows) == 2
        assert rows[-1].value == pytest.approx(2.75)
        assert rows[-1].currency == "CAD"

    def test_fred_ca_boc_rate_normalize(self):
        payload = (FIXTURES / "fred_ca_boc_rate_sample.json").read_text(encoding="utf-8")
        config = _config(
            "fred_ca_boc_rate",
            "rate",
            "BOC_OVERNIGHT_RATE",
            "adapter:fred_ca:IRSTCB01CAM156N",
            "transform_boc_key_rate",
        )
        adapter = CentralBankAdapter(config)
        raw = build_raw_response(config, payload)
        rows = adapter.normalize(raw)
        assert rows[-1].value == pytest.approx(2.75)
        assert rows[-1].currency == "CAD"


class TestLoadMacroSnapshot:
    @pytest.mark.asyncio
    async def test_snapshot_reevaluates_latest_despite_stale_flag(self):
        from app.services.macro_registry.service import load_macro_snapshot

        now = datetime.now(timezone.utc)
        latest_time = now - timedelta(days=2)
        stale_row = MagicMock(
            instrument="VIX",
            source_id="fred_vix",
            value=20.0,
            currency=None,
            unit="index_points",
            release_time=latest_time,
            observation_time=latest_time,
            period=latest_time.strftime("%Y-%m-%d"),
            revision=0,
            confidence=0.8,
            raw_payload_hash="hash",
        )
        session = AsyncMock()
        registry_result = MagicMock()
        registry_result.scalars.return_value.all.return_value = [
            MagicMock(source_id="fred_vix", refresh_interval="0 22 * * 1-5"),
        ]
        session.execute = AsyncMock(return_value=registry_result)

        storage = MagicMock()
        storage.load_latest = AsyncMock(
            side_effect=lambda _session, instrument: stale_row if instrument == "VIX" else None
        )

        with patch("app.services.macro_registry.service.MacroStorageLayer", return_value=storage):
            snapshot = await load_macro_snapshot(session)

        assert snapshot.get("vix") == pytest.approx(20.0)


class TestNormalizationQualityFlagUpdate:
    @pytest.mark.asyncio
    async def test_existing_row_quality_flag_updated(self):
        layer = NormalizationLayer()
        session = AsyncMock()
        existing = MagicMock(revision=0, value=21.0, quality_flag="stale")
        session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=lambda: existing)
        )
        session.add = MagicMock()
        session.flush = AsyncMock()
        now = datetime.now(timezone.utc)
        obs = NormalizedObservation(
            instrument="CBR_KEY_RATE",
            source_id="cbr_key_rate",
            value=21.0,
            currency="RUB",
            unit="%",
            release_time=now,
            observation_time=now,
            period="2025-07",
            revision=0,
            confidence=0.8,
            raw_payload_hash="hash",
        )
        stored = await layer.persist_observations(
            session,
            raw_response_id=1,
            observations=[obs],
            quality_flags={(obs.instrument, obs.observation_time): "ok"},
        )
        assert stored == 0
        assert existing.quality_flag == "ok"
