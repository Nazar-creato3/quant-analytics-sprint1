import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");

describe("AUD-K-12 tokenized user copy", () => {
  it("uses Russian copy and hides venue/provider names", () => {
    const onboarding = readFileSync(join(SRC, "components/trading/TokenizedEquitiesOnboarding.tsx"), "utf8");
    const disclosure = readFileSync(join(SRC, "components/trading/TradingDisclosuresModal.tsx"), "utf8");
    expect(onboarding).toMatch(/Американские акции через токены/);
    expect(onboarding).not.toMatch(/Bybit/);
    expect(disclosure).toMatch(/Риски токенизированных акций/);
    expect(disclosure).toMatch(/Понятно, продолжить/);
    expect(disclosure).not.toMatch(/Alpha Vantage|Finnhub|Bybit|MEXC|NYSE|NASDAQ/);
  });
});
