import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { PartnerBlock } from "@/components/partners/PartnerBlock";

describe("partner offer", () => {
  it("shows the block and leaves the disclosure empty", () => {
    const html = renderToStaticMarkup(<PartnerBlock />);
    expect(html).toContain("Открыть счёт у партнёра");
    expect(html).toContain("Раскрытие: нет данных");
    expect(html).toContain("выключен");
    expect(html).not.toContain("купите");
    expect(html).not.toContain("продайте");
  });
});
