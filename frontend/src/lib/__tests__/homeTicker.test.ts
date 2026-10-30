import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { resolveHomeTicker } from "@/lib/homeTicker";

describe("resolveHomeTicker (AUD-K-06)", () => {
  it("does not fall back to AAPL", () => {
    expect(resolveHomeTicker("", undefined)).toBe("");
    expect(resolveHomeTicker(null, null)).toBe("");
    expect(resolveHomeTicker("SBER", "GAZP")).toBe("SBER");
    expect(resolveHomeTicker("", "GAZP")).toBe("GAZP");
  });

  it("keeps AAPL out of the dashboard source", () => {
    const src = readFileSync(
      resolve(__dirname, "../../components/operator/OperatorDashboard.tsx"),
      "utf8",
    );
    expect(src).not.toContain("AAPL");
    expect(src).toContain("resolveHomeTicker");
  });
});
