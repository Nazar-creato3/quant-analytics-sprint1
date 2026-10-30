import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");

describe("GA16-277 forecast accuracy copy", () => {
  it("does not show n= or naive baseline jargon", () => {
    const text = readFileSync(join(SRC, "app/forecast-accuracy/page.tsx"), "utf8");
    expect(text).not.toMatch(/n=\{/);
    expect(text).not.toMatch(/\(n=/);
    expect(text).not.toMatch(/наивн/);
  });
});
