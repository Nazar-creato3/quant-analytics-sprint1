import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import BetaAdminPage from "@/app/admin/beta/page";

describe("beta admin page", () => {
  it("requires a second factor and shows no secret", () => {
    const html = renderToStaticMarkup(<BetaAdminPage />);
    expect(html).toContain("Второй фактор обязателен");
    expect(html).toContain("Секреты: нет данных");
    expect(html).toContain("Лимит мест: нет данных");
    expect(html).not.toContain("купите");
    expect(html).not.toContain("рекомендуем");
    expect(html).not.toContain("@");
  });
});
