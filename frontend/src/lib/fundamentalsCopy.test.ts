import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");

describe("AUD-K-21 fundamentals copy", () => {
  it("does not show the data vendor or English metric groups", () => {
    const text = readFileSync(
      join(SRC, "components/terminal/panels/TerminalFundamentalsSnapshot.tsx"),
      "utf8",
    );
    expect(text).toMatch(/Показатели недоступны/);
    expect(text).toMatch(/Валовая маржа/);
    expect(text).not.toMatch(/FMP |Key Metrics|Gross mgn|metrics_source/);
  });
});
