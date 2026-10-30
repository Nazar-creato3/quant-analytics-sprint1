"use client";

import { useEffect, useRef } from "react";
import { useFreshnessClock } from "@/hooks/useLiveFreshness";
import { monotonicCountdownSeconds } from "@/lib/profit-projection";

/**
 * Tick a server-provided time_to_close between REST/WS polls without skew-reset jumps.
 * Re-syncs only when the server reports a lower remaining value (monotonic clamp).
 */
export function usePositionExpiryCountdown(
  maneuverId: string,
  timeToClose: number | null | undefined,
  syncedAtMs: number | null,
  horizonExpired?: boolean | null,
): number | null {
  const clientNow = useFreshnessClock(1000);
  const baseRef = useRef<Map<string, { base: number; at: number }>>(new Map());

  useEffect(() => {
    if (horizonExpired) return;
    if (typeof timeToClose !== "number" || syncedAtMs == null) return;
    const prev = baseRef.current.get(maneuverId)?.base;
    const synced = monotonicCountdownSeconds(timeToClose, prev);
    baseRef.current.set(maneuverId, { base: synced, at: syncedAtMs });
  }, [maneuverId, timeToClose, syncedAtMs, horizonExpired]);

  if (horizonExpired) return 0;
  if (typeof timeToClose !== "number") return null;
  const anchor = baseRef.current.get(maneuverId);
  if (!anchor) return Math.max(0, timeToClose);
  const elapsed = Math.floor((clientNow - anchor.at) / 1000);
  return Math.max(0, anchor.base - elapsed);
}
