import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");

describe("GA16-307 cockpit vol bands", () => {
  it("does not default missing vol bands to zeros or show sigma 0", () => {
    const view = readFileSync(join(SRC, "components/cockpit/AssetCockpitView.tsx"), "utf8");
    const chart = readFileSync(join(SRC, "components/cockpit/AssetCockpitChart.tsx"), "utf8");
    expect(view).not.toMatch(/DEFAULT_VOL_BANDS/);
    expect(view).not.toMatch(/realized_vol:\s*0/);
    expect(chart).not.toMatch(/σ \{/);
    expect(chart).toMatch(/do not invent zero vol bands/);
  });
});
