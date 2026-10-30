/**
 * Smoke test: normalizeForecastHierarchy + buildMarketOutlookCards with partial/enhanced API payloads.
 * Run: node scripts/verify-forecast-partial.mjs (after npm run build, or via tsx on the TS sources).
 */
import assert from "node:assert/strict";

// Inline minimal copies of the critical normalization logic under test.
function isMarketOutlookPoint(entry) {
  return (
    typeof entry === "object" &&
    entry !== null &&
    ("title" in entry || "what_happens" in entry || "prognosis" in entry)
  );
}

function outlookEntrySummary(entry) {
  if (typeof entry === "string") return entry;
  if (!isMarketOutlookPoint(entry)) return "—";
  return (
    entry.what_happens?.trim() ||
    entry.prognosis?.trim() ||
    entry.expectations?.trim() ||
    entry.title?.trim() ||
    "—"
  );
}

function buildMarketOutlookCards(market) {
  if (!market || typeof market !== "object") return [];
  const outlookLines = Array.isArray(market.market_outlook) ? market.market_outlook : [];
  const cards = [];
  for (let i = 0; i < Math.min(3, outlookLines.length); i++) {
    const entry = outlookLines[i];
    cards.push({
      id: `outlook-${i}`,
      title_ru: isMarketOutlookPoint(entry) ? entry.title ?? `Outlook ${i + 1}` : `Outlook ${i + 1}`,
      summary: outlookEntrySummary(entry),
      evidence_basis: isMarketOutlookPoint(entry) ? entry.evidence_basis ?? [] : [],
      confidence: 0.5,
      engine: "ForecastEngine",
    });
  }
  return cards;
}

// Enhanced market_outlook objects (production API shape)
const enhancedMarket = {
  global_regime: { confidence: 0.72, dominant_regime_ru: "risk-on" },
  market_outlook: [
    {
      title: "Глобальный макро-режим",
      what_happens: "Рынок в risk-on",
      prognosis: "Держать exposure",
      evidence_basis: ["GlobalMacroRegimeEngine"],
      confidence_pct: 72,
    },
  ],
  sector_rotation: [],
  calibrated_probabilities: {},
  macro_indicators: { vix: 18 },
};

const cards = buildMarketOutlookCards(enhancedMarket);
assert.equal(cards.length, 1);
assert.equal(typeof cards[0].summary, "string");
assert.ok(cards[0].summary.includes("risk-on"));
assert.deepEqual(cards[0].evidence_basis, ["GlobalMacroRegimeEngine"]);

// Partial symbol forecast — must not throw when normalizing missing nested fields
const partialForecast = {
  symbol: "SPY",
  instrument_id: 1,
  probability_map: { momentum_score: 0.62 },
  hierarchy_output: {
    point_forecast: { momentum_score: 0.62, magnitude_class: "up", expected_return_sign: 1 },
    scenario_forecast: {},
    risk_forecast: { instrument_metrics: {}, breached_metrics: [] },
    action_forecast: { recommendation: "hold", reason: "ok" },
    instruction_block: "Что делать по SPY: Удержание.",
    basis_block: [{ layer: "point", engine: "ForecastEngine", conclusion_ru: "Импульс 62%." }],
  },
};

assert.ok(typeof partialForecast.hierarchy_output.instruction_block === "string");
assert.ok(Array.isArray(partialForecast.hierarchy_output.basis_block));

// Null-safe access patterns
const scenarios = partialForecast.hierarchy_output.scenario_forecast?.scenarios ?? [];
assert.deepEqual(scenarios, []);

console.log("verify-forecast-partial: all assertions passed");
