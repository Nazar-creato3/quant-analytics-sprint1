import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");

describe("AUD-K-15 analysis unavailable copy", () => {
  it("does not name the analysis vendor or show a balance", () => {
    const errors = readFileSync(join(SRC, "lib/errors.ts"), "utf8");
    const chip = readFileSync(join(SRC, "components/layout/LlmStatusIndicator.tsx"), "utf8");
    expect(errors).toMatch(/Анализ временно недоступен/);
    expect(errors).not.toMatch(/AITunnel/);
    expect(chip).toMatch(/ИИ ограничен/);
    expect(chip).not.toMatch(/AI ограничен/);
    expect(chip).not.toMatch(/balance_rub/);
    expect(chip).not.toMatch(/message_ru/);
  });
});
