import { describe, expect, it } from "vitest";
import { formatFmpReturnOn, formatFmpShare } from "@/lib/fmp-percent";

describe("formatFmpShare", () => {
  it("treats 0-1 as a ratio", () => {
    expect(formatFmpShare(0.25)).toBe("25.0%");
  });

  it("leaves already-percent margins alone", () => {
    expect(formatFmpShare(31)).toBe("31.0%");
  });
});

describe("formatFmpReturnOn", () => {
  it("scales 1.47 ROE to 147%", () => {
    expect(formatFmpReturnOn(1.47)).toBe("147.0%");
  });

  it("scales 0.28 ROIC to 28%", () => {
    expect(formatFmpReturnOn(0.28)).toBe("28.0%");
  });

  it("does not treat 28.5 as 2850%", () => {
    expect(formatFmpReturnOn(28.5)).toBe("28.5%");
  });
});
