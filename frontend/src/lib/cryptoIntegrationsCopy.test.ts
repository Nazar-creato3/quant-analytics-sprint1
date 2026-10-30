import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");

describe("GA16-318 crypto integrations copy", () => {
  it("is Russian and hides Swagger/module/wired and raw errors", () => {
    const text = readFileSync(join(SRC, "app/ops/crypto-integrations/page.tsx"), "utf8");
    expect(text).toMatch(/Интеграции/);
    expect(text).not.toMatch(/Swagger/);
    expect(text).not.toMatch(/wired:/);
    expect(text).not.toMatch(/row\.module/);
    expect(text).not.toMatch(/truncateEngineError\(row\.error\)/);
    expect(text).not.toMatch(/\$\{row\.error\}/);
    expect(text).not.toMatch(/Action\/proxy failed/);
  });
});
