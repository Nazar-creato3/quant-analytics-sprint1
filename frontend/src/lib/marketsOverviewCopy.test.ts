import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");

describe("GA16-313 markets overview copy", () => {
  it("does not show source, EOD, or Stooq to the user", () => {
    const text = readFileSync(join(SRC, "components/markets/MarketsOverview.tsx"), "utf8");
    expect(text).not.toMatch(/Stooq/);
    expect(text).not.toMatch(/EOD/);
    expect(text).not.toMatch(/data\?\.source/);
    expect(text).not.toMatch(/d_us_txt\.zip/);
  });
});
