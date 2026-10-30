import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");

describe("GA16-315 platform mandate copy", () => {
  it("uses generic mandate error and no IPS/Deploy/Sharpe labels", () => {
    const text = readFileSync(join(SRC, "app/platform/page.tsx"), "utf8");
    expect(text).toMatch(/Не удалось сохранить мандат/);
    expect(text).not.toMatch(/String\(saveIps\.error\)/);
    expect(text).not.toMatch(/IPS \/ mandate/);
    expect(text).not.toMatch(/Deploy cap/);
    expect(text).not.toMatch(/>\s*Sharpe\s*</);
    expect(text).not.toMatch(/Sharpe,/);
  });
});
