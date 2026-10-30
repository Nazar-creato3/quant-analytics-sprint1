import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { LEGAL_LINKS, LegalFooter } from "@/components/layout/LegalFooter";

describe("LegalFooter", () => {
  const html = renderToStaticMarkup(<LegalFooter />);

  it("is folded into one line by default", () => {
    expect(html).toContain("<details");
    expect(html).not.toContain("<details open");
    expect(html).toContain("Документы");
  });

  it("keeps every document link in the markup while folded", () => {
    for (const l of LEGAL_LINKS) expect(html).toContain(`href="${l.href}"`);
  });

  it("keeps the not-a-recommendation note and the age mark visible", () => {
    const summary = html.slice(html.indexOf("<summary"), html.indexOf("</summary>"));
    expect(summary).toContain("Не является инвестиционной рекомендацией");
    expect(summary).toContain("18+");
  });
});
