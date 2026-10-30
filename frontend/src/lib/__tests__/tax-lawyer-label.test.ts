import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

describe("tax block lawyer line", () => {
  it("does not show the internal lawyer marker", () => {
    const src = readFileSync(resolve(__dirname, "../../components/portfolio/blocks.tsx"), "utf8");
    expect(src).toContain("методика не подтверждена юристом");
    expect(src).not.toContain("[ЮРИСТ]");
    expect(src).not.toContain("lawyer_gate");
  });
});
