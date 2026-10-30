import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");

describe("AUD-K-10 ops error copy", () => {
  it("hides API/status codes from the user", () => {
    const integ = readFileSync(join(SRC, "app/ops/crypto-integrations/page.tsx"), "utf8");
    const health = readFileSync(join(SRC, "app/ops/connector-health/page.tsx"), "utf8");
    expect(integ).not.toMatch(/Trading engines API/);
    expect(integ).not.toMatch(/crypto_stack/);
    expect(integ).not.toMatch(/\(403\)/);
    expect(integ).not.toMatch(/\(404\)/);
    expect(integ).toMatch(/Не удалось загрузить данные/);
    expect(health).not.toMatch(/Failed to load connector health/);
    expect(health).toMatch(/Не удалось загрузить данные/);
  });
});
