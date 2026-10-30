import type { Maneuver } from "@/types";
import { durationHorizonExpiredLabel, type DurationLocale } from "@/lib/duration-i18n";

export function formatUsdPnl(value: number): string {
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  const abs = Math.abs(value);
  const digits = abs > 0 && abs < 100 ? 2 : 0;
  return `${sign}$${abs.toLocaleString("en", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`;
}

/** Model-aligned expected P&L band for remaining horizon (not full TP). */
export function formatExpectedPnlRange(m: Maneuver): string {
  if (m.expected_pnl_low != null && m.expected_pnl_high != null) {
    return `${formatUsdPnl(m.expected_pnl_low)}…${formatUsdPnl(m.expected_pnl_high)}`;
  }
  return "—";
}

export function formatTpHitProbability(m: Maneuver): string {
  if (m.tp_hit_probability == null) return "—";
  return `${Math.round(m.tp_hit_probability * 100)}%`;
}

/** Text color for probability metrics (aligned with ConfidenceBar thresholds). */
export function probabilityConfidenceTextClass(probability: number | null | undefined): string {
  if (probability == null) return "text-qa-muted";
  const pct = Math.round(probability * 100);
  if (pct >= 70) return "text-terminal-up";
  if (pct >= 55) return "text-terminal-accent";
  return "text-terminal-down";
}

/** Text color for model expected P&L band midpoint / sign. */
export function expectedPnlRangeTextClass(m: Maneuver): string {
  if (m.expected_pnl_low == null || m.expected_pnl_high == null) return "text-qa-muted";
  if (m.expected_pnl_low >= 0 && m.expected_pnl_high >= 0) return "text-terminal-up";
  if (m.expected_pnl_low <= 0 && m.expected_pnl_high <= 0) return "text-terminal-down";
  return "text-terminal-accent";
}

/** Zero-padded two-digit helper for countdown segments. */
function pad2(n: number): string {
  return String(Math.max(0, Math.floor(n))).padStart(2, "0");
}

/**
 * Format remaining seconds honestly: visible seconds under 1d, days above 1d.
 * Display always includes a ticking seconds segment so refresh resets are obvious.
 */
export function formatExpiryCountdown(totalSeconds: number, locale: DurationLocale = "ru"): string {
  if (!Number.isFinite(totalSeconds) || totalSeconds <= 0) return durationHorizonExpiredLabel(locale);
  const wholeSeconds = Math.floor(totalSeconds);
  const days = Math.floor(wholeSeconds / 86_400);
  const hours = Math.floor((wholeSeconds % 86_400) / 3600);
  const minutes = Math.floor((wholeSeconds % 3600) / 60);
  const seconds = wholeSeconds % 60;
  if (days > 0) return `${days}d ${pad2(hours)}:${pad2(minutes)}:${pad2(seconds)}`;
  return `${pad2(hours)}:${pad2(minutes)}:${pad2(seconds)}`;
}

/**
 * Single server-now reference: map client clock to server time using one snapshot anchor.
 * All countdown ticks derive from this — avoids backwards jumps when server_now refreshes.
 */
export function serverAlignedNowMs(
  serverNowIso: string | null | undefined,
  fetchedAtMs: number | null | undefined,
  clientNowMs: number,
): number {
  if (!serverNowIso || fetchedAtMs == null) return clientNowMs;
  const serverNow = Date.parse(serverNowIso);
  if (!Number.isFinite(serverNow)) return clientNowMs;
  const skewMs = fetchedAtMs - serverNow;
  return clientNowMs - skewMs;
}

/** Remaining seconds from an absolute expiry and absolute now. */
export function computeRemainingTime(
  expiresAtIso: string | null | undefined,
  nowMs: number,
): number | null {
  if (!expiresAtIso) return null;
  const expiresAt = Date.parse(expiresAtIso);
  if (!Number.isFinite(expiresAt) || !Number.isFinite(nowMs)) return null;
  return Math.max(0, Math.floor((expiresAt - nowMs) / 1000));
}

/** Remaining seconds until server-trusted expiry, corrected for clock skew. */
export function remainingSecondsFromExpiry(
  expiresAtIso: string,
  serverNowIso: string | null | undefined,
  clientNowMs: number,
  fetchedAtMs: number | null | undefined,
): number {
  const adjustedNow = serverAlignedNowMs(serverNowIso, fetchedAtMs, clientNowMs);
  return computeRemainingTime(expiresAtIso, adjustedNow) ?? 0;
}

/** Countdown must never increase between ticks (guards poll/WS skew resets). */
export function monotonicCountdownSeconds(
  computed: number,
  previous: number | undefined,
): number {
  if (!Number.isFinite(computed) || computed <= 0) return 0;
  if (previous == null || !Number.isFinite(previous)) return computed;
  return Math.min(previous, computed);
}

export function formatTimeToCloseHonest(
  value: number | string | null | undefined,
  horizonExpired?: boolean | null,
  locale: DurationLocale = "ru",
): string {
  if (horizonExpired) return durationHorizonExpiredLabel(locale);
  if (value == null || value === "") return "—";
  if (typeof value === "string") {
    // Legacy pre-formatted strings from older API builds — pass through.
    if (value.startsWith("~")) return value;
    return value;
  }
  if (!Number.isFinite(value) || value <= 0) return durationHorizonExpiredLabel(locale);
  return formatExpiryCountdown(value, locale);
}
