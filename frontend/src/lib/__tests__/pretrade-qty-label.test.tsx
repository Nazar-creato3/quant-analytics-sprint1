import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

describe("pre-trade check inside the order ticket", () => {
  it("says what the quantity counts instead of a bare «Количество»", () => {
    const src = readFileSync(resolve(__dirname, "../../components/orders/OrderTicket.tsx"), "utf8");
    expect(src).toContain("Сколько купить");
    expect(src).toContain("шт. бумаг");
    expect(src).toContain("<PretradeImpact");
    expect(src).not.toContain(">Qty<");
  });

  it("labels check blocks in Russian instead of internal keys", () => {
    const src = readFileSync(resolve(__dirname, "../../components/orders/PretradeImpact.tsx"), "utf8");
    const labels = readFileSync(resolve(__dirname, "../actPreviewInputs.ts"), "utf8");
    expect(labels).toContain('factors: "Факторы"');
    expect(src).toContain("PRETRADE_BLOCK_LABELS[k]");
    expect(src).toContain("Как сделка изменит портфель");
  });
});
