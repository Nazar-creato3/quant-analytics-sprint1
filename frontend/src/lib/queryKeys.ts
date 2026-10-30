/** Shared React Query keys so every surface reads the same cache entry. */

export const queryKeys = {
  regime: (ticker?: string) => ["regime", ticker ?? "market"] as const,
  forecastCore: (ticker: string) => ["forecast-core", ticker] as const,
  forecastMarket: ["forecast-market"] as const,
  forecastRanks: ["forecast-ranks"] as const,
  report: (userId: string, mode: "paper" | "live") => ["report", userId, mode] as const,
  book: (userId: string, mode: "paper" | "live") => ["book", userId, mode] as const,
  stress: (userId: string, mode: "paper" | "live") => ["stress-library", userId, mode] as const,
  concentration: (userId: string, mode: "paper" | "live") => ["concentration", userId, mode] as const,
  lookthrough: (userId: string, mode: "paper" | "live", view: string) =>
    ["lookthrough", userId, mode, view] as const,
  behavior: (userId: string, mode: "paper" | "live") => ["behavior", userId, mode] as const,
  portfolioMetrics: (userKey: string | undefined) => ["user", userKey ?? "anonymous", "portfolio-metrics"] as const,
  returns: (userId: string, mode: "paper" | "live") => ["returns", userId, mode] as const,
  simpleAlts: (userId: string, mode: "paper" | "live") => ["simple-alts", userId, mode] as const,
  composer: (userId: string, mode: "paper" | "live") => ["strategy-composer", userId, mode] as const,
} as const;
