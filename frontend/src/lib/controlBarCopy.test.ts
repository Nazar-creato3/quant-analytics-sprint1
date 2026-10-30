import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");

describe("GA16-254 control bar copy", () => {
  it("uses Russian mode and link labels and does not draw an empty venue", () => {
    const text = readFileSync(join(SRC, "components/operator/ControlBar.tsx"), "utf8");
    expect(text).toMatch(/Учебный/);
    expect(text).toMatch(/Боевой/);
    expect(text).toMatch(/База/);
    expect(text).toMatch(/Кэш/);
    expect(text).not.toMatch(/>Paper<|>Live<|>DB<|>Cache<|>Venue</);
  });
});
