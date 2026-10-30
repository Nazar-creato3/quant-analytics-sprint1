import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");

describe("AUD-K-22 terminal sidebar copy", () => {
  it("uses Russian section labels", () => {
    const text = readFileSync(join(SRC, "components/terminal/TerminalSidebar.tsx"), "utf8");
    expect(text).toMatch(/Рынок/);
    expect(text).toMatch(/Разделы терминала/);
    expect(text).not.toMatch(/QA Terminal|AI workflows|Staff \/ operators|label: "Market"/);
  });
});
