import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

describe("public methodology text", () => {
  it("does not name libraries, flags, or internal paths", () => {
    const src = readFileSync(resolve(__dirname, "../public-methodology.ts"), "utf8");
    for (const token of ["QuantStats", "Meucci", "total_return", "K4", "K6", "[ЮРИСТ]", "/methodology/", "CVaR", "TWR", "G-спред"]) {
      expect(src).not.toContain(token);
    }
    expect(src).toContain("нет данных");
  });
});
