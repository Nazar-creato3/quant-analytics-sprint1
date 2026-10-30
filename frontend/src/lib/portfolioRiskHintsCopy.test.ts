import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");

describe("GA16-334 portfolio risk hints", () => {
  it("does not expose FHS/EWMA/GET /risk/S&P or dollar signs in helpers", () => {
    const text = readFileSync(
      join(SRC, "components/portfolio/PortfolioRiskProfileView.tsx"),
      "utf8",
    );
    expect(text).not.toMatch(/FHS/);
    expect(text).not.toMatch(/EWMA/);
    expect(text).not.toMatch(/GET \/risk/);
    expect(text).not.toMatch(/S&P/);
    expect(text).not.toMatch(/`\$\$\{/);
  });
});
