export type ManeuverDedupeRow = {
  id: string;
  ticker: string;
  direction?: string | null;
  confidence?: number | null;
  rationale?: string | null;
  status?: string | null;
  created_at?: string | null;
};

const STATUS_RANK: Record<string, number> = {
  pending: 5,
  approved: 4,
  executing: 3,
  filled: 2,
  rejected: 1,
};

export function maneuverContentKey(row: ManeuverDedupeRow): string {
  const ticker = (row.ticker || "").trim().toUpperCase();
  const direction = String(row.direction || "").toLowerCase();
  const conf = row.confidence != null && Number.isFinite(row.confidence) ? row.confidence.toFixed(2) : "";
  const rationale = (row.rationale || "").replace(/\s+/g, " ").trim().slice(0, 200);
  return `${ticker}|${direction}|${conf}|${rationale}`;
}

/** Keep one row per identical content; prefer live statuses, then newest. */
export function dedupeManeuvers<T extends ManeuverDedupeRow>(rows: T[]): T[] {
  const byKey = new Map<string, T>();
  for (const row of rows) {
    const key = maneuverContentKey(row);
    const prev = byKey.get(key);
    if (!prev) {
      byKey.set(key, row);
      continue;
    }
    const prevRank = STATUS_RANK[(prev.status || "").toLowerCase()] ?? 0;
    const nextRank = STATUS_RANK[(row.status || "").toLowerCase()] ?? 0;
    if (nextRank > prevRank) {
      byKey.set(key, row);
      continue;
    }
    if (nextRank === prevRank) {
      const prevTs = Date.parse(prev.created_at || "") || 0;
      const nextTs = Date.parse(row.created_at || "") || 0;
      if (nextTs >= prevTs) byKey.set(key, row);
    }
  }
  return [...byKey.values()];
}
