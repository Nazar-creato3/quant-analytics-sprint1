import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

describe("report risk scale", () => {
  it("translates the traffic light and hides the raw status", () => {
    const src = readFileSync(resolve(__dirname, "../../components/market/PortfolioReportCard.tsx"), "utf8");
    expect(src).toContain('green: "спокойно"');
    expect(src).toContain("riskScale(first?.traffic_light, first?.risk_status)");
    expect(src).not.toContain("String(first.traffic_light)");
    expect(src).not.toContain("String(first.risk_status)");
    const profile = readFileSync(resolve(__dirname, "../../components/portfolio/PortfolioRiskProfileView.tsx"), "utf8");
    expect(profile).not.toContain("Единый риск-сервис");
    expect(profile).not.toContain("светофор");
    const overview = readFileSync(resolve(__dirname, "../../components/portfolio/OverviewBlock.tsx"), "utf8");
    expect(overview).toContain('green: { text: "Спокойный"');
  });
});
