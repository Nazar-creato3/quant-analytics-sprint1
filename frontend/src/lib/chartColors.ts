/**
 * Chart color constants — literal hex/rgba for lightweight-charts & recharts APIs.
 * Keep in sync with Design Token Layer in `src/app/globals.css`.
 * Runtime reads via cssToken(); static CHART_COLORS are SSR / fallback only.
 */

/** Resolve a CSS custom property to a hex/rgb string (browser only). */
export function cssToken(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

/** Read chart palette from design tokens at mount time; falls back to synced literals. */
export function readChartColors(): ChartColorPalette {
  return {
    success: cssToken("--color-success", CHART_COLORS.success),
    danger: cssToken("--color-danger", CHART_COLORS.danger),
    accent: cssToken("--color-accent", CHART_COLORS.accent),
    primary: cssToken("--color-primary", CHART_COLORS.primary),
    textMuted: cssToken("--color-text-secondary", CHART_COLORS.textMuted),
    panel: cssToken("--cockpit-panel", CHART_COLORS.panel),
    border: cssToken("--color-border", CHART_COLORS.border),
    gridLine: cssToken("--cockpit-border", CHART_COLORS.gridLine),
    crosshair: cssToken("--chart-crosshair", CHART_COLORS.crosshair),
    crosshairLabel: cssToken("--chart-crosshair-label", CHART_COLORS.crosshairLabel),
    entryLine: cssToken("--color-accent", CHART_COLORS.entryLine),
    liveNeutral: cssToken("--chart-live-neutral", CHART_COLORS.liveNeutral),
    volumeUp: cssToken("--chart-volume-up", CHART_COLORS.volumeUp),
    volumeDown: cssToken("--chart-volume-down", CHART_COLORS.volumeDown),
    rangeBand: cssToken("--chart-range-band", CHART_COLORS.rangeBand),
    volBand: cssToken("--chart-vol-band", CHART_COLORS.volBand),
    volMid: cssToken("--color-text-secondary", CHART_COLORS.volMid),
    forecastBand: cssToken("--chart-forecast-band", CHART_COLORS.forecastBand),
    positiveBar: cssToken("--color-success", CHART_COLORS.positiveBar),
    negativeBar: cssToken("--color-danger", CHART_COLORS.negativeBar),
    volumeBar: cssToken("--chart-volume-bar", CHART_COLORS.volumeBar),
    alertBg: cssToken("--chart-alert-bg", CHART_COLORS.alertBg),
    alertText: cssToken("--chart-alert-text", CHART_COLORS.alertText),
    alertBorder: cssToken("--chart-alert-border", CHART_COLORS.alertBorder),
  };
}

/** Static literals — dark theme defaults for SSR / fallback. */
export const CHART_COLORS = {
  success: "#00C853",
  danger: "#FF5252",
  accent: "#F5A623",
  primary: "#F5A623",
  textMuted: "#9A9A9A",
  panel: "#121212",
  border: "#242424",
  gridLine: "#242424",
  crosshair: "#333333",
  crosshairLabel: "#0B0B0B",
  entryLine: "#F5A623",
  liveNeutral: "#F2F2F2",
  volumeUp: "rgba(0, 200, 83, 0.45)",
  volumeDown: "rgba(255, 82, 82, 0.45)",
  rangeBand: "rgba(245, 166, 35, 0.35)",
  volBand: "rgba(245, 166, 35, 0.25)",
  volMid: "#9A9A9A",
  forecastBand: "rgba(245, 166, 35, 0.4)",
  positiveBar: "#00C853",
  negativeBar: "#FF5252",
  volumeBar: "#242424",
  alertBg: "#3b1212",
  alertText: "#FF5252",
  alertBorder: "#FF5252",
} as const;

export type ChartColorPalette = { [K in keyof typeof CHART_COLORS]: string };
