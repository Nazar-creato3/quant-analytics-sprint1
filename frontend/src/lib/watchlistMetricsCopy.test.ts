import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");

describe("GA16-256 watchlist metrics", () => {
  it("uses Russian labels and does not default to N/A or dollars", () => {
    const text = readFileSync(join(SRC, "components/operator/WatchlistTickerPanel.tsx"), "utf8");
    expect(text).toMatch(/Капитализация/);
    expect(text).toMatch(/нет данных/);
    expect(text).toMatch(/Рыночные показатели/);
    expect(text).not.toMatch(/N\/A/);
    expect(text).not.toMatch(/Market Cap|Key Market Stats|Div Yield/);
    // old compact USD: `$${(n / 1e12)...}`
    expect(text).not.toMatch(/\$\$\{/);
  });
});
