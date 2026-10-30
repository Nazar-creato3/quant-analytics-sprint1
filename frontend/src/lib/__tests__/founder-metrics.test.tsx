import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import FounderMetricsPage from "@/app/admin/analytics/page";

describe("founder metrics page", () => {
  it("does not invent a product metric", () => {
    const html = renderToStaticMarkup(<FounderMetricsPage />);
    expect(html).toContain("Активация: нет данных");
    expect(html).toContain("Воронка манёвров: нет данных");
    expect(html).toContain("Сводка Slack: нет данных");
    expect(html).toContain("Выгрузка повторяет эти строки.");
    expect(html).not.toContain("купите");
    expect(html).not.toContain("рекомендуем");
    expect(html).not.toContain("%");
    expect(html).not.toContain("@");
  });
});
