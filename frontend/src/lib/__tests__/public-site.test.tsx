import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { LegalSlot } from "@/components/site/LegalSlot";
import { PublicSiteHome } from "@/components/site/PublicSiteHome";
import { AWAITING_COPY, accuracyLines } from "@/lib/public-site";

describe("public site", () => {
  it("keeps founder and legal slots unpublished", () => {
    const html = renderToStaticMarkup(<PublicSiteHome />);
    expect(html).toContain("<h1");
    expect(html).toContain("Проблема");
    expect(html).toContain("Текст основателя: нет данных.");
    expect(html).toContain(AWAITING_COPY);
    expect(html).toContain("Платёж на этой странице не принимается");
    expect(html).toContain('href="/methodology"');
    expect(html).not.toContain("купите");
    expect(html).not.toContain("продайте");
    expect(html).not.toContain("рекомендуем");
    expect(accuracyLines()[1]).toBe("Опубликованная точность: нет данных.");
    const legal = renderToStaticMarkup(<LegalSlot title="Согласие на обработку" />);
    expect(legal).toContain("Текст не опубликован.");
    expect(legal).toContain(AWAITING_COPY);
    expect(legal).toContain("<h1");
  });
});
