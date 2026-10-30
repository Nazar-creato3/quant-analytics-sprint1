import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

describe("calculation screens hide timing", () => {
  it("does not print milliseconds on bonds or risk", () => {
    const bonds = readFileSync(resolve(__dirname, "../../components/portfolio/BondsPanel.tsx"), "utf8");
    const risk = readFileSync(resolve(__dirname, "../../components/portfolio/RiskAttributionPanel.tsx"), "utf8");
    expect(bonds).not.toContain("мс");
    expect(risk).not.toContain("k4-elapsed");
    expect(risk).not.toContain("elapsed_ms");
  });
});
