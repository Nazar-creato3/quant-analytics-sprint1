import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

describe("brain now panel", () => {
  it("shows the dashboard block with source link and empty state", () => {
    const src = readFileSync(resolve(__dirname, "../../components/operator/BrainNow.tsx"), "utf8");
    expect(src).toContain('data-testid="brain-now"');
    expect(src).toContain("Главное сейчас");
    expect(src).toContain("Открыть модуль");
    expect(src).toContain("нет данных");
    expect(src).not.toContain("купите");
    expect(src).not.toContain("продайте");
  });
});
