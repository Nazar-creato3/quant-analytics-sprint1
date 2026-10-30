import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");

describe("AUD-K-18 terminal column copy", () => {
  it("uses Russian column labels and hides quote reasons", () => {
    const portfolio = readFileSync(join(SRC, "components/terminal/widgets/PortfolioPanel.tsx"), "utf8");
    const indices = readFileSync(join(SRC, "components/terminal/widgets/GlobalIndicesPanel.tsx"), "utf8");
    const factors = readFileSync(join(SRC, "components/terminal/widgets/QuantFactorsPanel.tsx"), "utf8");
    expect(portfolio).toMatch(/>Инструмент</);
    expect(portfolio).not.toMatch(/>Sym</);
    expect(indices).toMatch(/>Сессия</);
    expect(indices).not.toMatch(/quote unavailable|>N\/A</);
    expect(indices).not.toMatch(/title=\{r\.reason/);
    expect(factors).toMatch(/>Свежесть</);
    expect(factors).not.toMatch(/Source \/ fresh/);
  });
});
