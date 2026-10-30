import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { quoteChangeTone } from "./WatchlistRowCard";

describe("GA16-245 watchlist row", () => {
  it("does not treat a missing change as a gain", () => {
    expect(quoteChangeTone(null)).toBe("flat");
    expect(quoteChangeTone(undefined)).toBe("flat");
    expect(quoteChangeTone(Number.NaN)).toBe("flat");
    expect(quoteChangeTone(0)).toBe("flat");
    expect(quoteChangeTone(1.2)).toBe("up");
    expect(quoteChangeTone(-0.4)).toBe("down");
  });

  it("does not show Volume, Collapse, or tap hints", () => {
    const text = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "WatchlistRowCard.tsx"), "utf8");
    expect(text).not.toMatch(/Volume|Collapse|Tap symbol/);
  });
});
