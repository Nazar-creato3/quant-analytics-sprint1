import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { OrderMarginNote } from "@/components/orders/OrderMarginNote";

describe("order margin note", () => {
  it("shows missing broker figures and keeps live off", () => {
    const html = renderToStaticMarkup(<OrderMarginNote />);
    expect(html).toContain("Обеспечение: нет данных");
    expect(html).toContain("Плечо: нет данных");
    expect(html).toContain("Цена ликвидации: нет данных");
    expect(html).toContain("Реальный режим выключен");
    expect(html).not.toContain("купите");
    expect(html).not.toContain("продайте");
  });
});
