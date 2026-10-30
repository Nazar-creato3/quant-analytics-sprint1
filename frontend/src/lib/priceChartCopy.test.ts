import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");

describe("AUD-K-09 PriceChart tooltip copy", () => {
  it("uses Russian OHLC labels", () => {
    const text = readFileSync(join(SRC, "components/charts/PriceChart.tsx"), "utf8");
    expect(text).toMatch(/>Открытие</);
    expect(text).toMatch(/>Макс\.</);
    expect(text).toMatch(/>Мин\.</);
    expect(text).toMatch(/>Закрытие</);
    expect(text).toMatch(/>Изменение</);
    expect(text).toMatch(/>Объём</);
    expect(text).not.toMatch(/>Open</);
    expect(text).not.toMatch(/>High</);
    expect(text).not.toMatch(/>Volume</);
  });
});
