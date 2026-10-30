import { describe, expect, it } from "vitest";
import { dedupeManeuvers, maneuverContentKey } from "@/lib/maneuver-dedupe";

describe("dedupeManeuvers", () => {
  it("collapses identical MSFT theses and keeps pending", () => {
    const rows = dedupeManeuvers([
      {
        id: "1",
        ticker: "MSFT",
        direction: "short",
        confidence: 0.52,
        rationale: "RSI 56 MACD bearish",
        status: "rejected",
      },
      {
        id: "2",
        ticker: "MSFT",
        direction: "short",
        confidence: 0.52,
        rationale: "RSI 56 MACD bearish",
        status: "pending",
      },
      {
        id: "3",
        ticker: "ETH-USD",
        direction: "long",
        confidence: 0.4,
        rationale: "other",
        status: "pending",
      },
    ]);
    expect(rows).toHaveLength(2);
    expect(rows.find((r) => r.ticker === "MSFT")?.id).toBe("2");
  });

  it("does not merge different tickers", () => {
    expect(
      maneuverContentKey({ id: "a", ticker: "MSFT", rationale: "x" })
        === maneuverContentKey({ id: "b", ticker: "ETH", rationale: "x" }),
    ).toBe(false);
  });
});
