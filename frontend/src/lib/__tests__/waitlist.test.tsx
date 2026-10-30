import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { WaitlistCard } from "@/components/site/WaitlistCard";

describe("waitlist card", () => {
  it("keeps consent unpublished and the preorder off", () => {
    const html = renderToStaticMarkup(<WaitlistCard />);
    expect(html).toContain("Лист ожидания");
    expect(html).toContain("Согласие: нет данных");
    expect(html).toContain("Текст не опубликован.");
    expect(html).toContain("Предзаказ выключен");
    expect(html).toContain("Цена: нет данных");
    expect(html).toContain('name="company_website"');
    expect(html).not.toContain("купите");
    expect(html).not.toContain("продайте");
  });
});
