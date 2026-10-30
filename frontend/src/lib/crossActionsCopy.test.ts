import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");

describe("GA16-251 cross actions", () => {
  it("does not offer an AI ask or a paper composer bot", () => {
    const text = readFileSync(join(SRC, "components/shared/CrossActions.tsx"), "utf8");
    expect(text).toMatch(/Влияние на портфель/);
    expect(text).not.toMatch(/Спросить ИИ|Composer|mode=paper/);
  });
});
