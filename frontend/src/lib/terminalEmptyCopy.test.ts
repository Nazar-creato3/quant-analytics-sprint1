import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");

const FILES = [
  "components/terminal/widgets/QuantFactorsPanel.tsx",
  "components/terminal/widgets/PortfolioPanel.tsx",
  "components/terminal/widgets/PerformancePanel.tsx",
  "components/terminal/widgets/MarketPulsePanel.tsx",
  "components/terminal/widgets/MarketHoursPanel.tsx",
  "components/terminal/widgets/GlobalIndicesPanel.tsx",
];

describe("AUD-K-17 terminal empty copy", () => {
  it("does not show English empty hints or route names", () => {
    for (const rel of FILES) {
      const text = readFileSync(join(SRC, rel), "utf8");
      expect(text, rel).not.toMatch(/EmptyHint text="[A-Za-z]/);
      expect(text, rel).not.toMatch(/\/terminal\//);
      expect(text, rel).not.toMatch(/Fear & Greed|VIX|OHLCV/);
    }
  });
});
