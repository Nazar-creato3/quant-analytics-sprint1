"""Aggregate market-level forecast for GET /forecast/market."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import InstrumentSource
from app.domain.instrument import InstrumentORM
from app.domain.market_data import MarketOhlcvORM, SectorMappingORM
from app.services.macro_registry.service import load_macro_snapshot, load_macro_snapshot_bundle
from app.services.forecast.market_prediction_narrator import (
    MarketCoverage,
    MarketPredictionNarrator,
)
from app.services.forecast.scenario_disclosure_narrator import ScenarioDisclosureNarrator
from app.services.macro.sector_seed import SECTOR_SEED
from app.services.prediction_hierarchy.global_regime import compute_cross_asset_correlation
from app.services.prediction_hierarchy.orchestrator import get_hierarchy_orchestrator
from app.services.prediction_hierarchy.sector_regime import SectorRegimeEngine
from app.services.prediction_hierarchy.types import GlobalRegimeLabel, SectorRotationFlag
from app.services.regime.features import prices_to_returns
from app.services.regime.types import InstrumentSeries

_GLOBAL_RU: dict[str, str] = {
    GlobalRegimeLabel.RISK_ON.value: "режим риска (risk-on)",
    GlobalRegimeLabel.RISK_OFF.value: "режим защиты (risk-off)",
    GlobalRegimeLabel.MACRO_UNCERTAINTY.value: "макро-неопределённость",
    GlobalRegimeLabel.CREDIT_STRESS.value: "стресс на кредитном рынке",
    GlobalRegimeLabel.INFLATION_SHOCK_REGIME.value: "инфляционный шок",
}

_ROTATION_RU: dict[str, str] = {
    SectorRotationFlag.SECTORS_STRENGTHENING.value: "секторы усиливаются",
    SectorRotationFlag.SECTORS_WEAKENING.value: "секторы ослабевают",
    SectorRotationFlag.ROTATION_IN_PROGRESS.value: "ротация секторов в процессе",
    SectorRotationFlag.NEUTRAL.value: "нейтральная ротация",
}

_SECTOR_RU: dict[str, str] = {
    "technology": "технологии",
    "financials": "финансы",
    "energy": "энергетика",
    "consumer_discretionary": "потребительский сектор",
    "communication_services": "коммуникации",
    "indices": "индексы",
    "macro_hedge": "макро-хедж",
    "digital_assets": "цифровые активы",
    "materials": "материалы",
}


async def _load_macro_indicators(db: AsyncSession) -> dict[str, float]:
    return await load_macro_snapshot(db)


async def _load_sector_returns(db: AsyncSession) -> tuple[dict[str, list[float]], list[float]]:
    stmt = (
        select(MarketOhlcvORM)
        .where(MarketOhlcvORM.timeframe == "1d")
        .order_by(MarketOhlcvORM.time.desc())
        .limit(800)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    by_instrument: dict[int, list[float]] = {}
    for row in rows:
        if row.close is None:
            continue
        by_instrument.setdefault(row.instrument_id, []).append(float(row.close))
    for prices in by_instrument.values():
        prices.reverse()

    mapping_stmt = select(SectorMappingORM)
    mappings = list((await db.execute(mapping_stmt)).scalars().all())
    sector_prices: dict[str, list[float]] = {}
    for mapping in mappings:
        prices = by_instrument.get(mapping.instrument_id, [])
        if not prices:
            continue
        sector_prices.setdefault(mapping.sector, []).extend(prices[-63:])

    sector_returns: dict[str, list[float]] = {}
    for sector, prices in sector_prices.items():
        if len(prices) >= 5:
            sector_returns[sector] = prices_to_returns(prices)

    spy_prices = by_instrument.get(_spy_instrument_id(mappings), [])
    market_returns = prices_to_returns(spy_prices) if len(spy_prices) >= 5 else []
    return sector_returns, market_returns


def _spy_instrument_id(mappings: list[SectorMappingORM]) -> int | None:
    for mapping in mappings:
        if mapping.sector == "indices":
            return mapping.instrument_id
    return None


def _pct(probability: float) -> float:
    return round(max(0.0, min(1.0, probability)) * 100.0, 1)


async def _detect_market_coverage(
    db: AsyncSession,
    mappings: list[SectorMappingORM],
    sector_returns: dict[str, list[float]],
) -> MarketCoverage:
    """Detect which exchanges have real OHLCV-backed sector data."""
    instrument_ids = {m.instrument_id for m in mappings}
    if not instrument_ids:
        return MarketCoverage(markets=())

    stmt = select(InstrumentORM).where(InstrumentORM.id.in_(instrument_ids))
    instruments = list((await db.execute(stmt)).scalars().all())

    moex_symbols: list[str] = []
    us_symbols: list[str] = []
    crypto_symbols: list[str] = []
    markets: list[str] = []

    for inst in instruments:
        sector = next((m.sector for m in mappings if m.instrument_id == inst.id), None)
        if sector not in sector_returns or len(sector_returns.get(sector, [])) < 3:
            continue
        if inst.source == InstrumentSource.MOEX:
            moex_symbols.append(inst.symbol)
        elif inst.source in (InstrumentSource.FINAM, InstrumentSource.TINKOFF):
            us_symbols.append(inst.symbol)
        elif inst.source == InstrumentSource.BINANCE:
            crypto_symbols.append(inst.symbol)

    if moex_symbols:
        markets.append("MOEX")
    if us_symbols:
        markets.append("US_equities")
    if crypto_symbols:
        markets.append("crypto")

    return MarketCoverage(
        markets=tuple(markets),
        moex_symbols=tuple(sorted(set(moex_symbols))),
        us_symbols=tuple(sorted(set(us_symbols))),
        crypto_symbols=tuple(sorted(set(crypto_symbols))),
    )


def _outlook_point_to_dict(point: Any) -> dict[str, Any]:
    return {
        "title": point.title,
        "what_happens": point.what_happens,
        "how": point.how,
        "where": point.where,
        "expectations": point.expectations,
        "prognosis": point.prognosis,
        "evidence_basis": list(point.evidence_basis),
        "confidence_pct": point.confidence_pct,
    }


def _build_market_outlook_points(
    global_result: Any,
    macro: dict[str, float],
    rotation_scores: list[Any],
) -> list[dict[str, Any]]:
    """Build exactly 3 detailed market outlook points."""
    from app.services.prediction_hierarchy.types import MarketOutlookPoint

    dominant_ru = _GLOBAL_RU.get(global_result.dominant_regime, global_result.dominant_regime)
    dom_prob = global_result.distribution.get(global_result.dominant_regime, 0.0)
    risk_off_prob = global_result.distribution.get(GlobalRegimeLabel.RISK_OFF.value, 0.0)
    vix = macro.get("vix")
    cpi = macro.get("cpi")
    rate_cb = macro.get("rate_cb")

    macro_evidence = [
        f"GlobalMacroRegimeEngine: dominant={global_result.dominant_regime}",
        f"global_regime.confidence={global_result.confidence:.2f}",
        f"prob_{global_result.dominant_regime}={dom_prob:.2f}",
    ]
    if vix is not None:
        macro_evidence.append(f"macro_indicators.vix={vix:.1f}")
    if cpi is not None:
        macro_evidence.append(f"macro_indicators.cpi={cpi:.2f}")
    if rate_cb is not None:
        macro_evidence.append(f"macro_indicators.rate_cb={rate_cb:.2f}")
    if global_result.credit_spread_proxy is not None:
        macro_evidence.append(f"credit_spread_proxy={global_result.credit_spread_proxy:.4f}")

    vix_note = ""
    if vix is not None:
        if vix >= 30:
            vix_note = f"VIX {vix:.1f} — стрессовый уровень, риск-активы под давлением."
        elif vix <= 18:
            vix_note = f"VIX {vix:.1f} — спокойный фон, допустим умеренный риск."
        else:
            vix_note = f"VIX {vix:.1f} — нейтральная волатильность."

    point1 = MarketOutlookPoint(
        title="Глобальный макро-режим и риск-аппетит",
        what_happens=(
            f"Рынок находится в режиме «{dominant_ru}» с вероятностью {_pct(dom_prob)}%. "
            f"{vix_note}"
        ),
        how=(
            "GlobalMacroRegimeEngine агрегирует VIX, CPI, ставку ЦБ, DXY, нефть и "
            "кросс-активную корреляцию в вероятностное распределение режимов."
        ),
        where="Глобальные индексы (SPY/QQQ), облигации, USD, сырьевые активы",
        expectations=(
            f"Risk-off вероятность {_pct(risk_off_prob)}%. "
            + (
                f"Инфляция (CPI proxy {cpi:.1f}%) поддерживает инфляционный сценарий."
                if cpi is not None and cpi > 3.0
                else "Инфляционное давление умеренное."
            )
        ),
        prognosis=(
            "При сохранении доминирующего режима — "
            + (
                "предпочтительна защитная allocation и снижение бета-экспозиции."
                if global_result.dominant_regime in {"risk_off", "credit_stress", "macro_uncertainty"}
                else "умеренное наращивание риска возможно при контроле хвостов."
            )
        ),
        evidence_basis=tuple(macro_evidence),
        confidence_pct=round(global_result.confidence * 100, 1),
    )

    leader_ru = "—"
    lagger_ru = "—"
    leader_flag = "нейтральная"
    leader_score = 0.0
    sector_evidence: list[str] = ["SectorRegimeEngine.rank_sectors()"]
    if rotation_scores:
        leader = rotation_scores[0]
        lagger = rotation_scores[-1]
        leader_ru = _SECTOR_RU.get(leader.sector, leader.sector)
        lagger_ru = _SECTOR_RU.get(lagger.sector, lagger.sector)
        leader_flag = _ROTATION_RU.get(leader.rotation_flag.value, leader.rotation_flag.value)
        leader_score = leader.composite_score
        sector_evidence.extend(
            [
                f"sector_leader={leader.sector}",
                f"rotation_flag={leader.rotation_flag.value}",
                f"composite_score_1m={leader.composite_score:.4f}",
                f"score_1w={leader.score_1w:.4f}",
                f"score_3m={leader.score_3m:.4f}",
            ]
        )

    point2 = MarketOutlookPoint(
        title="Секторная ротация и относительная сила",
        what_happens=(
            f"Лидер ротации — {leader_ru} ({leader_flag}), "
            f"отстаёт {lagger_ru}. "
            f"Опережение рынка за 1 мес.: {leader_score * 100:.1f} б.п."
            if rotation_scores
            else "Данных по секторной ротации недостаточно — нейтральная картина."
        ),
        how=(
            "SectorRegimeEngine сравнивает доходности секторов на горизонтах 1н/1м/3м "
            "относительно SPY и классифицирует флаг ротации."
        ),
        where=f"Секторы: {', '.join(_SECTOR_RU.get(s.sector, s.sector) for s in rotation_scores[:4]) or 'широкий рынок'}",
        expectations=(
            "Капитал продолжит смещаться в лидирующие секторы при сохранении тренда ротации."
            if rotation_scores and rotation_scores[0].rotation_flag != SectorRotationFlag.SECTORS_WEAKENING
            else "Возможна защитная ротация в defensive-секторы."
        ),
        prognosis=(
            f"Фокус на {leader_ru} при подтверждении импульса; "
            f"избегать перегруза {lagger_ru}."
            if rotation_scores
            else "Диверсификация по секторам до появления явного лидера."
        ),
        evidence_basis=tuple(sector_evidence),
        confidence_pct=round(min(0.95, 0.55 + abs(leader_score) * 2) * 100, 1),
    )

    vol_evidence = [
        "ForecastEngine.volatility_expansion_probability (market proxy)",
        f"cross_asset_correlation={macro.get('cross_asset_correlation', 'n/a')}",
    ]
    if vix is not None:
        vol_evidence.append(f"macro_indicators.vix={vix:.1f}")

    vol_regime = "умеренная"
    vol_prognosis = "Диапазон колебаний в пределах исторической нормы."
    if vix is not None:
        if vix >= 28:
            vol_regime = "повышенная"
            vol_prognosis = "Ожидается расширение дневных диапазонов; хеджи и снижение плеча оправданы."
        elif vix <= 16:
            vol_regime = "низкая"
            vol_prognosis = "Благоприятный фон для carry и умеренного риска; следить за внезапными макро-сюрпризами."

    point3 = MarketOutlookPoint(
        title="Волатильность и диапазон рыночных исходов",
        what_happens=f"Текущий волатильностный фон: {vol_regime}. {vix_note or 'VIX data unavailable.'}",
        how=(
            "Интервал прогноза строится из исторической волатильности (ForecastOutputBuilder) "
            "и стресс-сценариев ScenarioEngine (rate_shock, vix_spike, correlation_breakdown)."
        ),
        where="Индексы, волатильность (VIX), процентные ставки, кредитные спреды",
        expectations=(
            "Широкий диапазон исходов при risk-off >25% или VIX>25; "
            "сужение диапазона при risk-on и низком VIX."
        ),
        prognosis=vol_prognosis,
        evidence_basis=tuple(vol_evidence),
        confidence_pct=round(
            (0.70 if vix is not None else 0.50) * (global_result.confidence + 0.15) * 100 / 1.15,
            1,
        ),
    )

    return [
        _outlook_point_to_dict(point1),
        _outlook_point_to_dict(point2),
        _outlook_point_to_dict(point3),
    ]


async def _aggregate_archetype_probabilities(
    db: AsyncSession,
    symbols: tuple[str, ...],
) -> dict[str, float] | None:
    """Average narrative archetype weights from hierarchy forecasts on key symbols."""
    if not symbols:
        return None

    from app.services.instrument.resolver import resolve_or_create_instrument
    from app.services.prediction_hierarchy.orchestrator import get_hierarchy_orchestrator

    orchestrator = get_hierarchy_orchestrator()
    buckets: dict[str, list[float]] = {key: [] for key in ("pessimistic", "realistic", "optimistic", "classic")}

    for symbol in symbols[:5]:
        try:
            instrument = await resolve_or_create_instrument(db, symbol)
            hierarchy = await orchestrator.get_forecast(
                db,
                instrument.id,
                symbol=instrument.symbol,
                include_narrative=False,
                use_cache=True,
            )
            for scenario in hierarchy.scenario_forecast.scenarios:
                if scenario.scenario_type in buckets:
                    buckets[scenario.scenario_type].append(float(scenario.probability))
        except Exception:
            continue

    if not any(buckets.values()):
        return None

    averaged = {
        key: round(sum(values) / len(values), 4) if values else 0.0
        for key, values in buckets.items()
    }
    total = sum(averaged.values())
    if total <= 0:
        return None
    return {key: round(value / total, 4) for key, value in averaged.items()}


async def build_market_forecast(db: AsyncSession) -> dict[str, Any]:
    """Aggregate macro regime, sector rotation, and top market outlook points."""
    as_of = datetime.now(timezone.utc)
    macro_bundle = await load_macro_snapshot_bundle(db)
    macro = macro_bundle.get("indicators") or {}
    sector_returns, market_returns = await _load_sector_returns(db)

    mapping_stmt = select(SectorMappingORM)
    mappings = list((await db.execute(mapping_stmt)).scalars().all())

    cross_asset: list[list[float]] = []
    for returns in list(sector_returns.values())[:4]:
        if len(returns) >= 5:
            cross_asset.append(returns)
    cross_asset_corr = compute_cross_asset_correlation(cross_asset)

    orchestrator = get_hierarchy_orchestrator()
    global_result = await orchestrator.classify_global_macro(
        db,
        macro,
        asset_returns=cross_asset,
    )

    sector_engine = SectorRegimeEngine()
    rotation_scores = sector_engine.rank_sectors(
        sector_returns or {sector: [] for sector in {s[0] for s in SECTOR_SEED.values()}},
        market_returns,
    )

    dominant_ru = _GLOBAL_RU.get(global_result.dominant_regime, global_result.dominant_regime)
    outlook = _build_market_outlook_points(global_result, macro, rotation_scores)

    calibrated = {
        label: round(prob, 4)
        for label, prob in sorted(
            global_result.distribution.items(),
            key=lambda item: item[1],
            reverse=True,
        )
    }

    sector_rotation = [
        {
            "sector": score.sector,
            "sector_ru": _SECTOR_RU.get(score.sector, score.sector),
            "rank": score.rank,
            "composite_score": score.composite_score,
            "score_1w": score.score_1w,
            "score_1m": score.score_1m,
            "score_3m": score.score_3m,
            "rotation_flag": score.rotation_flag.value,
            "rotation_flag_ru": _ROTATION_RU.get(
                score.rotation_flag.value,
                score.rotation_flag.value,
            ),
        }
        for score in rotation_scores
    ]

    coverage = await _detect_market_coverage(db, mappings, sector_returns)
    summary = MarketPredictionNarrator().synthesize(
        global_result=global_result,
        macro=macro,
        rotation_scores=rotation_scores,
        coverage=coverage,
        cross_asset_correlation=cross_asset_corr,
    )

    aggregate_symbols = ("SPY", "QQQ", "BTC-USD")
    if coverage.moex_symbols:
        aggregate_symbols = (*aggregate_symbols, coverage.moex_symbols[0])
    aggregated_archetypes = await _aggregate_archetype_probabilities(db, aggregate_symbols)

    disclosure = ScenarioDisclosureNarrator().from_market_engines(
        macro=macro,
        macro_bundle=macro_bundle,
        global_result=global_result,
        rotation_scores=rotation_scores,
        aggregated_archetypes=aggregated_archetypes,
    )

    return {
        "as_of": as_of.isoformat(),
        "global_regime": {
            "dominant_regime": global_result.dominant_regime,
            "dominant_regime_ru": dominant_ru,
            "confidence": global_result.confidence,
            "distribution": calibrated,
            "credit_spread_proxy": global_result.credit_spread_proxy,
        },
        "market_outlook": outlook,
        "sector_rotation": sector_rotation,
        "calibrated_probabilities": calibrated,
        "macro_indicators": macro,
        "market_prediction_summary": summary.to_dict(),
        "scenario_disclosure": disclosure.to_dict(),
    }
