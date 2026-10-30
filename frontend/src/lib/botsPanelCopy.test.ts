import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");

describe("AUD-K-16 bots panel copy", () => {
  it("uses Russian labels and hides internal names", () => {
    const text = readFileSync(join(SRC, "components/bots/BotsPanel.tsx"), "utf8");
    expect(text).toMatch(/Пока нет ботов/);
    expect(text).toMatch(/Фильтр/);
    expect(text).toMatch(/STATUS_LABEL/);
    expect(text).not.toMatch(/No bots yet/);
    expect(text).not.toMatch(/>Start</);
    expect(text).not.toMatch(/RobotPlan|runtime|Shadow/);
    expect(text).not.toMatch(/toast\.error\(error\.message\)/);
  });
});
