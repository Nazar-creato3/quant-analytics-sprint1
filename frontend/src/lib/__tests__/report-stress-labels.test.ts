import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

describe("report stress labels", () => {
  it("shows the scenario title instead of the internal id", () => {
    const src = readFileSync(resolve(__dirname, "../../components/market/PortfolioReportCard.tsx"), "utf8");
    expect(src).toContain('String(row.title || "сценарий")');
    expect(src).toContain("{label}");
    expect(src).not.toContain('row.id || row.name || "scen"');
  });
});
