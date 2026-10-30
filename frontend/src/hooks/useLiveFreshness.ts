"use client";

import { useEffect, useMemo, useState } from "react";

/** Data older than this is considered stale (seconds). */
export const STALE_DATA_SEC = 45;
/** Data older than this is considered disconnected (seconds). */
export const DISCONNECTED_DATA_SEC = 120;

export type DataFreshnessState = "live" | "stale" | "disconnected" | "unknown";

export function freshnessFromTimestamp(
  lastUpdateAt: number | null,
  now = Date.now(),
): DataFreshnessState {
  if (lastUpdateAt == null) return "unknown";
  const ageSec = (now - lastUpdateAt) / 1000;
  if (ageSec <= STALE_DATA_SEC) return "live";
  if (ageSec <= DISCONNECTED_DATA_SEC) return "stale";
  return "disconnected";
}

export function formatFreshnessAge(lastUpdateAt: number | null, now = Date.now()): string {
  if (lastUpdateAt == null) return "—";
  const sec = Math.max(0, Math.round((now - lastUpdateAt) / 1000));
  if (sec < 60) return `${sec} с назад`;
  if (sec < 3600) return `${Math.floor(sec / 60)} мин назад`;
  return `${Math.floor(sec / 3600)} ч назад`;
}

/** Re-render every second so freshness labels tick. */
export function useFreshnessClock(intervalMs = 1_000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

/**
 * Client clock mapped to server time via a single (server_now, fetched_at) anchor.
 * Pass the same anchor for the whole snapshot — do not mix poll vs WS anchors per row.
 */
export function useServerAlignedNow(
  serverNowIso: string | null | undefined,
  fetchedAtMs: number | null | undefined,
): number {
  const clientNow = useFreshnessClock();
  if (!serverNowIso || fetchedAtMs == null) return clientNow;
  const serverNow = Date.parse(serverNowIso);
  if (!Number.isFinite(serverNow)) return clientNow;
  const skewMs = fetchedAtMs - serverNow;
  return clientNow - skewMs;
}

export function useDataFreshness(lastUpdateAt: number | null) {
  const now = useFreshnessClock();
  return useMemo(
    () => ({
      state: freshnessFromTimestamp(lastUpdateAt, now),
      ageLabel: formatFreshnessAge(lastUpdateAt, now),
      ageSec: lastUpdateAt != null ? Math.round((now - lastUpdateAt) / 1000) : null,
    }),
    [lastUpdateAt, now],
  );
}

/** Client-side countdown: server gave N seconds remaining at fetch time. */
export function useLiveCountdown(
  baseSeconds: number | null | undefined,
  fetchedAt: number | null,
): number | null {
  const now = useFreshnessClock();
  if (baseSeconds == null || fetchedAt == null) return baseSeconds ?? null;
  const elapsed = Math.floor((now - fetchedAt) / 1000);
  return Math.max(0, baseSeconds - elapsed);
}

export function formatCountdown(seconds: number | null): string {
  if (seconds == null) return "—";
  if (seconds <= 0) return "expired";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}
