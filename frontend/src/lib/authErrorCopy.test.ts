import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");

describe("AUD-K-14 auth error copy", () => {
  it("does not show raw API text or English fallbacks", () => {
    const signup = readFileSync(join(SRC, "app/signup/page.tsx"), "utf8");
    const apply = readFileSync(join(SRC, "app/apply/page.tsx"), "utf8");
    const admissions = readFileSync(join(SRC, "app/operator/admissions/page.tsx"), "utf8");
    const security = readFileSync(join(SRC, "app/admin/security/page.tsx"), "utf8");

    expect(signup).toMatch(/Не удалось зарегистрироваться/);
    expect(signup).not.toMatch(/: msg,/);
    expect(apply).toMatch(/Не удалось отправить заявку/);
    expect(apply).not.toMatch(/JSON\.stringify/);
    expect(admissions).not.toMatch(/Create failed/);
    expect(admissions).toMatch(/Не удалось создать/);
    expect(security).not.toMatch(/Invalid code/);
    expect(security).toMatch(/Код не подошёл/);
    expect(security).not.toMatch(/MFA включена/);
  });
});
