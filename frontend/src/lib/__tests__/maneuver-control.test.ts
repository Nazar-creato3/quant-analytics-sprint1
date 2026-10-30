import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ManeuverControlBlock } from "@/components/act/ManeuverControlBlock";
import { controlLines, kindLabel } from "@/lib/maneuver-control";

describe("maneuver control labels", () => {
  it("prints нет данных instead of an empty number", () => {
    const lines = controlLines({ kind: "reduce_weight", actual_return: null, expected_return: "0.06" });
    expect(lines[0]).toBe("снижение доли");
    expect(lines.join(" ")).toContain("нет данных");
    expect(kindLabel("unknown-kind")).toBe("нет данных");
    const html = renderToStaticMarkup(createElement(ManeuverControlBlock, { status: "нет данных", items: [] }));
    expect(html).toContain("нет данных");
    expect(html).toContain('id="maneuver-control-title"');
  });
});
