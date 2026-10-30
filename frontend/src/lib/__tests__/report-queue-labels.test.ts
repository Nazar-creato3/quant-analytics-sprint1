import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

describe("report queue labels", () => {
  it("does not print internal queue keys or ready/beta", () => {
    const src = readFileSync(resolve(__dirname, "../../components/market/PortfolioReportCard.tsx"), "utf8");
    expect(src).toContain('q1_composition: "состав"');
    expect(src).toContain("QUEUE_LABEL[k]");
    expect(src).toContain('return "есть данные"');
    expect(src).not.toContain("{k}:");
    expect(src).not.toContain('(бета)');
  });
});
