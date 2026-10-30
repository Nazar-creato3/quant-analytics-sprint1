import { describe, expect, it } from "vitest";
import { formatMlSignal, mlSignalFromForecast } from "@/lib/ml-forecast-signal";
import type { ForecastData } from "@/types";

describe("formatMlSignal", () => {
  it("renders up with percent", () => {
    const view = formatMlSignal({
      symbol: "AAPL",
      direction: "up",
      confidence: 0.72,
      source: "forecast_engine",
    });
    expect(view.text).toBe("▲ 72%");
    expect(view.cls).toContain("up");
  });

  it("keeps ML column empty only when engine has no row", () => {
    expect(formatMlSignal(undefined).text).toBe("—");
    expect(formatMlSignal({ symbol: "X", direction: "neutral", confidence: null, reason: "unavailable" }).text).toBe("—");
  });
});

describe("mlSignalFromForecast", () => {
  it("uses calibrated confidence, not point momentum", () => {
    const signal = mlSignalFromForecast("aapl", {
      symbol: "AAPL",
      calibrated_confidence: 0.41,
      hierarchy_output: {
        calibrated_confidence: 0.41,
        point_forecast: { direction: "up", momentum_score: 0.72, expected_return_sign: 1 },
      },
    } as unknown as ForecastData);
    expect(signal?.confidence).toBe(0.41);
    expect(signal?.direction).toBe("up");
  });
});
