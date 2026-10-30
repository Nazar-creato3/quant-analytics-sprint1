/** React-query keys invalidated when live book / portfolio metrics refresh. */
export const LIVE_POSITION_QUERY_KEYS = [
  "bottom-positions",
  "bottom-fills",
  "operator-open-positions",
  "maneuvers-open-positions",
  "portfolio-metrics",
] as const;
