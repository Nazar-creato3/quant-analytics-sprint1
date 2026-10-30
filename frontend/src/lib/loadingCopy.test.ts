import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");

const FILES = [
  "components/trading/TokenizedEquitiesOnboarding.tsx",
  "components/settings/TradingAccountsPanel.tsx",
  "components/orders/OrderTicketModal.tsx",
  "app/ops/crypto-integrations/page.tsx",
  "app/ops/connector-health/page.tsx",
];

describe("AUD-K-08 loading copy", () => {
  it("uses Russian loading text instead of English Loading", () => {
    for (const rel of FILES) {
      const text = readFileSync(join(SRC, rel), "utf8");
      expect(text, rel).not.toMatch(/["'`]Loading/);
      expect(text, rel).toMatch(/Загрузка/);
    }
  });
});
