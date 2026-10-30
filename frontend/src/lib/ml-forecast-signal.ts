import type { ForecastMlSignal } from "@/lib/api";
import type { ForecastData } from "@/types";
import { normalizeForecastHierarchy, pct } from "@/lib/forecast-hierarchy";

/** Direction from point layer; % is Forecast header calibrated confidence. */
export function mlSignalFromForecast(
  symbol: string,
  data: ForecastData | null | undefined,
): ForecastMlSignal | null {
  if (!data) return null;
  const view = normalizeForecastHierarchy(data);
  const confidence = view.calibrated_confidence;
  return {
    symbol: symbol.toUpperCase(),
    direction: view.point_forecast.direction,
    confidence: Number.isFinite(confidence) ? confidence : null,
    source: "forecast_engine",
  };
}

export function formatMlSignal(signal: ForecastMlSignal | undefined | null): {
  text: string;
  cls: string;
  title: string;
} {
  if (!signal || signal.reason === "unavailable") {
    return { text: "—", cls: "text-terminal-muted", title: "Forecast engine ещё не посчитал сигнал" };
  }
  const arrow = signal.direction === "up" ? "▲" : signal.direction === "down" ? "▼" : "■";
  const cls =
    signal.direction === "up"
      ? "text-terminal-up"
      : signal.direction === "down"
        ? "text-terminal-down"
        : "text-terminal-muted";
  const shown = pct(signal.confidence);
  return {
    text: `${arrow} ${shown}`,
    cls,
    title: `Calibrated ${shown} · ${signal.direction} · same as Forecast header`,
  };
}
