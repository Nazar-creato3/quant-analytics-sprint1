export const ACTIVE_TICKER_STORAGE_KEY = "qa:active-ticker";
export const DEFAULT_ACTIVE_TICKER = "SBER";

import { catalogNormalize } from "@/lib/catalog";

/** Normalize a typed/pasted ticker via catalog rules (Prompt 03). */
export function normalizeActiveTicker(raw: string | null | undefined): string {
  if (!(raw ?? "").trim()) return DEFAULT_ACTIVE_TICKER;
  return catalogNormalize(raw).symbol || DEFAULT_ACTIVE_TICKER;
}

export function readStoredActiveTicker(): string {
  if (typeof window === "undefined") return DEFAULT_ACTIVE_TICKER;
  try {
    const stored = sessionStorage.getItem(ACTIVE_TICKER_STORAGE_KEY);
    return stored ? normalizeActiveTicker(stored) : DEFAULT_ACTIVE_TICKER;
  } catch {
    return DEFAULT_ACTIVE_TICKER;
  }
}

export function writeStoredActiveTicker(ticker: string): void {
  if (typeof window === "undefined") return;
  try {
    sessionStorage.setItem(ACTIVE_TICKER_STORAGE_KEY, normalizeActiveTicker(ticker));
  } catch {
    /* ignore quota / private mode */
  }
}
