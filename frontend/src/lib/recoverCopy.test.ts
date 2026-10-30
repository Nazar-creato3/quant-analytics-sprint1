import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");

describe("GA16-278 recover error copy", () => {
  it("does not surface exception message to the user", () => {
    const text = readFileSync(join(SRC, "app/recover/page.tsx"), "utf8");
    expect(text).not.toMatch(/err\.message/);
    expect(text).not.toMatch(/Error \? err\.message/);
    expect(text).toMatch(/Не удалось отправить запрос/);
  });
});
