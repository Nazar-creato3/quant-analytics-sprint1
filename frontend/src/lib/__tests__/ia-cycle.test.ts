import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { IA_CYCLE, IA_CYCLE_HREFS } from "@/lib/iaCycle";
import { queryKeys } from "@/lib/queryKeys";

const CYCLE_ORDER = ["learn", "evaluate", "risk", "act", "control", "service"];

describe("IA cycle", () => {
  it("follows TZ user cycle and keeps service secondary", () => {
    expect(IA_CYCLE.map((g) => g.id)).toEqual(CYCLE_ORDER);
    expect(IA_CYCLE_HREFS).toContain("/forecasting");
    expect(IA_CYCLE_HREFS).toContain("/portfolio");
    expect(IA_CYCLE_HREFS).toContain("/direct-deals");
    expect(IA_CYCLE_HREFS).toContain("/act");
  });

  it("does not let cycle pages recompute portfolio numbers locally", () => {
    const roots = [
      "frontend/src/app/portfolio-risk/page.tsx",
      "frontend/src/app/portfolio-report/page.tsx",
      "frontend/src/components/market/PortfolioReportCard.tsx",
    ];
    for (const rel of roots) {
      const root = process.cwd().replace(/[\\/]frontend$/, "");
      const text = readFileSync(resolve(root, rel), "utf8");
      expect(text.includes("hhi *") || text.includes("twr =")).toBe(false);
    }
  });
});

describe("queryKeys", () => {
  it("separates paper and live cache entries", () => {
    expect(queryKeys.report("demo", "paper")).not.toEqual(queryKeys.report("demo", "live"));
    expect(queryKeys.book("demo", "paper")[2]).toBe("paper");
  });
});
