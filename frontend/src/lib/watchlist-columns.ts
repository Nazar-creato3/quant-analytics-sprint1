export type OptionalWatchColumn = "price" | "change" | "pe" | "pb" | "mcap" | "beta" | "rsi" | "sma";

export const OPTIONAL_WATCH_COLUMNS: Array<{ id: OptionalWatchColumn; label: string; group: "price" | "fmp" | "twelvedata" }> = [
  { id: "price", label: "Price", group: "price" },
  { id: "change", label: "%", group: "price" },
  { id: "pe", label: "P/E", group: "fmp" },
  { id: "pb", label: "P/B", group: "fmp" },
  { id: "mcap", label: "Mkt cap", group: "fmp" },
  { id: "beta", label: "Beta", group: "fmp" },
  { id: "rsi", label: "RSI", group: "twelvedata" },
  { id: "sma", label: "SMA20", group: "twelvedata" },
];

const STORAGE_KEY = "qa:terminal-watch-cols";
const DEFAULT_COLS: OptionalWatchColumn[] = ["price", "change", "pe", "rsi", "sma"];

export function readWatchColumns(): OptionalWatchColumn[] {
  if (typeof window === "undefined") return DEFAULT_COLS;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_COLS;
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return DEFAULT_COLS;
    const allowed = new Set(OPTIONAL_WATCH_COLUMNS.map((c) => c.id));
    return parsed.filter((id): id is OptionalWatchColumn => allowed.has(id));
  } catch {
    return DEFAULT_COLS;
  }
}

export function writeWatchColumns(cols: OptionalWatchColumn[]): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(cols));
  } catch {
    /* ignore */
  }
}
