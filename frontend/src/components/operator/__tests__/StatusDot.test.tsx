import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { StatusDot } from "@/components/operator/StatusDot";

describe("StatusDot hit target", () => {
  it("gives the risk explanation control at least 24px", () => {
    const html = renderToStaticMarkup(
      <StatusDot level="caution" label="Внимание" explanation="Лимит близок" />,
    );
    expect(html).toContain("<button");
    expect(html).toContain("min-h-6");
    expect(html).toContain("min-w-6");
    expect(html).not.toContain("p-0");
  });
});
