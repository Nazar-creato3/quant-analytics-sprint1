import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { parseQty, quoteToPrice } from "@/lib/actPreviewInputs";

describe("act/pretrade preview inputs (GA16-039)", () => {
  it("does not invent a price of 100 when the quote is missing", () => {
    expect(quoteToPrice(undefined)).toBeNull();
    expect(quoteToPrice({})).toBeNull();
    expect(quoteToPrice({ last: 0 })).toBeNull();
  });

  it("takes last or price from the quote", () => {
    expect(quoteToPrice({ last: 256.5 })).toBe("256.5");
    expect(quoteToPrice({ price: "12.3" })).toBe("12.3");
  });

  it("rejects empty or non-positive qty instead of defaulting to 1", () => {
    expect(parseQty("")).toBeNull();
    expect(parseQty("0")).toBeNull();
    expect(parseQty("2.5")).toBe("2.5");
  });

  it("does not hardcode preview qty 1 or price 100 on act/pretrade pages", () => {
    const act = readFileSync(resolve(__dirname, "../../app/act/page.tsx"), "utf8");
    const pre = readFileSync(resolve(__dirname, "../../app/pretrade/page.tsx"), "utf8");
    expect(act).not.toContain('qty: "1"');
    expect(act).not.toContain('price: "100"');
    expect(pre).not.toContain('price: "100"');
    expect(act).not.toMatch(/activeAccount \}/);
  });
});
