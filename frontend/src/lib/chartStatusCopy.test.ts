import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");

describe("AUD-K-20 chart status copy", () => {
  it("does not show OHLCV, API, Mock, or raw risk reasons", () => {
    const chart = readFileSync(join(SRC, "components/terminal/TerminalWorkspace.tsx"), "utf8");
    const shell = readFileSync(join(SRC, "components/terminal/TerminalShell.tsx"), "utf8");
    const risk = readFileSync(join(SRC, "components/terminal/panels/TerminalRiskDesk.tsx"), "utf8");
    expect(chart).toMatch(/График ждёт котировки/);
    expect(chart).not.toMatch(/OHLCV|Loading /);
    expect(shell).toMatch(/онлайн/);
    expect(shell).not.toMatch(/>API<|>Mock<|>Partial</);
    expect(risk).toMatch(/Оценка риска недоступна/);
    expect(risk).not.toMatch(/risk\.reason|Risk unavailable/);
  });
});
