import { describe, expect, it } from "vitest";
import { normalizeRuMobile } from "../PhoneCodeField";

describe("normalizeRuMobile", () => {
  it("accepts common spellings of a Russian mobile", () => {
    expect(normalizeRuMobile("+7 (912) 345-67-89")).toBe("+79123456789");
    expect(normalizeRuMobile("89123456789")).toBe("+79123456789");
    expect(normalizeRuMobile("9123456789")).toBe("+79123456789");
  });

  it("rejects landlines and foreign numbers", () => {
    expect(normalizeRuMobile("+7 495 123-45-67")).toBeNull();
    expect(normalizeRuMobile("+380501234567")).toBeNull();
    expect(normalizeRuMobile("")).toBeNull();
  });
});
