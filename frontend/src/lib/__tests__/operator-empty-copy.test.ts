import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

describe("operator empty/live copy (AUD-K-07)", () => {
  it("does not show N/A or Live to the user", () => {
    const watch = readFileSync(
      resolve(__dirname, "../../components/operator/WatchlistTickerPanel.tsx"),
      "utf8",
    );
    const chart = readFileSync(
      resolve(__dirname, "../../components/operator/MainChartPanel.tsx"),
      "utf8",
    );
    expect(watch).not.toContain("N/A");
    expect(watch).toContain("нет данных");
    expect(chart).not.toMatch(/"Live"|· Live/);
    expect(chart).toContain("онлайн");
  });
});
