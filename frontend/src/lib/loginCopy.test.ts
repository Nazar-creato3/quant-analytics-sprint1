import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");

describe("AUD-K-13 login copy", () => {
  it("does not name third-party authenticators", () => {
    const text = readFileSync(join(SRC, "app/login/page.tsx"), "utf8");
    expect(text).toMatch(/Подтвердите вход на этом устройстве/);
    expect(text).toMatch(/приложения двухфакторной защиты/);
    expect(text).toMatch(/Почта/);
    expect(text).not.toMatch(/Google Authenticator|Face ID|Touch ID|Windows Hello/);
  });
});
