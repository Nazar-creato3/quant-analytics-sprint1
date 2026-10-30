import { describe, expect, it } from "vitest";
import { newsMentionsTicker, textMatchesTicker } from "@/lib/ticker-text-match";

describe("textMatchesTicker", () => {
  it("does not treat C as a substring of CALL", () => {
    expect(textMatchesTicker("CALL option volume spikes", "C")).toBe(false);
  });

  it("matches a standalone ticker token", () => {
    expect(textMatchesTicker("AAPL beats estimates", "AAPL")).toBe(true);
    expect(textMatchesTicker("$META rally", "META")).toBe(true);
  });

  it("does not match META inside METALS", () => {
    expect(textMatchesTicker("METALS rebound overnight", "META")).toBe(false);
  });
});

describe("newsMentionsTicker", () => {
  it("trusts tickers_mentioned when present", () => {
    expect(newsMentionsTicker({ title: "CALL volume", tickers_mentioned: ["AAPL"] }, "C")).toBe(false);
    expect(newsMentionsTicker({ title: "Banks", tickers_mentioned: ["C"] }, "C")).toBe(true);
  });
});
