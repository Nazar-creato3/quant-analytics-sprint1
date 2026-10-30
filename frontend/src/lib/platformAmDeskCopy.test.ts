import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");

describe("GA16-349 AM Desk copy", () => {
  it("has no IPS/Tear/Brinson/RC/ESG labels on screen", () => {
    const text = readFileSync(join(SRC, "app/platform/page.tsx"), "utf8");
    expect(text).not.toMatch(/IPS \/ mandate/);
    expect(text).not.toMatch(/Tear \/ Brinson/);
    expect(text).not.toMatch(/>\s*Sharpe\s*</);
    expect(text).not.toMatch(/RC%/);
    expect(text).not.toMatch(/ESG keywords/);
    expect(text).toMatch(/Мандат/);
    expect(text).toMatch(/Клиентский отчёт/);
  });
});
