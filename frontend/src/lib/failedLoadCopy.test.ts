import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");

describe("AUD-K-11 failed-load copy", () => {
  it("does not show Failed to load or HTTP status to the user", () => {
    const files = [
      "components/cockpit/AssetCockpitView.tsx",
      "app/track-record/page.tsx",
      "components/trading/TokenizedEquitiesOnboarding.tsx",
      "components/trading/TradingDisclosuresModal.tsx",
    ];
    for (const rel of files) {
      const text = readFileSync(join(SRC, rel), "utf8");
      expect(text, rel).not.toMatch(/Failed to load/);
      expect(text, rel).not.toMatch(/HTTP \$\{/);
      expect(text, rel).toMatch(/Не удалось загрузить данные/);
    }
  });
});
