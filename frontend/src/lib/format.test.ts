import { describe, expect, it } from "vitest";
import { formatUsd } from "./format";

describe("GA16-252 amount format", () => {
  it("does not stamp a dollar sign or K/M on every amount", () => {
    const large = formatUsd(1_500_000);
    const mid = formatUsd(25_000);
    expect(large.replace(/\s/g, "")).toBe("1500000");
    expect(mid.replace(/\s/g, "")).toBe("25000");
    expect(large).not.toMatch(/\$|[KM]/);
    expect(mid).not.toMatch(/\$|[KM]/);
    expect(formatUsd(null)).toBe("—");
  });
});
