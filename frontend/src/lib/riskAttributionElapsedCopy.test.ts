import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");

describe("GA16-337 risk attribution elapsed", () => {
  it("does not show elapsed_ms to the user", () => {
    const text = readFileSync(
      join(SRC, "components/portfolio/RiskAttributionPanel.tsx"),
      "utf8",
    );
    expect(text).not.toMatch(/elapsed_ms/);
    expect(text).not.toMatch(/k4-elapsed/);
  });
});
