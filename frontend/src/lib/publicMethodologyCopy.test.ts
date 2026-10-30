import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");

describe("GA16-362 public methodology copy", () => {
  it("avoids QuantStats/CVaR/Meucci/lawyer-tag/index tickers", () => {
    const text = readFileSync(join(SRC, "lib/public-methodology.ts"), "utf8");
    expect(text).not.toMatch(/QuantStats/);
    expect(text).not.toMatch(/CVaR/);
    expect(text).not.toMatch(/Meucci/);
    expect(text).not.toMatch(/\[ЮРИСТ\]/);
    expect(text).not.toMatch(/RGBITR/);
  });
});
