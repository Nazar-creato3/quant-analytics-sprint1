import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");

describe("GA16-257 position detail money", () => {
  it("formats entry and size via instrument currency, not hardcoded dollars", () => {
    const text = readFileSync(join(SRC, "components/operator/PositionDetailModal.tsx"), "utf8");
    expect(text).toMatch(/formatInstrumentPrice/);
    expect(text).toMatch(/entryPriceLabel|positionSizeLabel/);
    expect(text).not.toMatch(/\$\{maneuver\.fill_price/);
    expect(text).not.toMatch(/\$\{maneuver\.entry_zone_high/);
    expect(text).not.toMatch(/\$\{maneuver\.position_size_usd/);
    expect(text).not.toMatch(/`\$\$\{maneuver/);
  });
});
