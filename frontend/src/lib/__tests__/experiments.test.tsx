import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import ExperimentsPage from "@/app/admin/experiments/page";

describe("experiments page", () => {
  it("does not start an experiment or name a winner", () => {
    const html = renderToStaticMarkup(<ExperimentsPage />);
    expect(html).toContain("Решение основателя: нет данных");
    expect(html).toContain("Эксперимент не запущен");
    expect(html).toContain("Победитель: нет данных");
    expect(html).not.toContain("купите");
    expect(html).not.toContain("рекомендуем");
    expect(html).not.toContain("@");
  });
});
