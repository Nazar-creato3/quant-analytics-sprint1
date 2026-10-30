import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "../../..");

describe("GA16-276 tax methodology copy", () => {
  it("does not expose file path, module name, or flag", () => {
    const text = readFileSync(join(ROOT, "legal/ui_texts.ru.yaml"), "utf8");
    const taxBlock = text.slice(text.indexOf("\ntax:"), text.indexOf("\ntax:") + 800);
    expect(taxBlock).not.toMatch(/docs\/methodology\/tax\.md/);
    expect(taxBlock).not.toMatch(/target_portfolio\.tax/);
    expect(taxBlock).not.toMatch(/qa_tax_rf/);
  });
});
