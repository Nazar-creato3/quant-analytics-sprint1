import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");

describe("AUD-K-19 companion dock copy", () => {
  it("hides the product name, script path, and release link", () => {
    const text = readFileSync(join(SRC, "components/terminal/TerminalCompanionDock.tsx"), "utf8");
    expect(text).toMatch(/Настольный терминал/);
    expect(text).toMatch(/Отправить список/);
    expect(text).not.toMatch(/Fincept Companion|Launch Fincept|Qt |AppData|github\.com|start-companion/);
  });
});
