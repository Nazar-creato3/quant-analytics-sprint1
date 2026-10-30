import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { MethodologyBody } from "@/components/methodology/MethodologyBody";

describe("public methodology", () => {
  it("states missing price, accuracy, and the unrun load test", () => {
    const html = renderToStaticMarkup(<MethodologyBody />);
    expect(html).toContain("Методика");
    expect(html).toContain("нет данных");
    expect(html).toContain("Цена подписки: нет данных");
    expect(html).not.toContain("купите");
    expect(html).not.toContain("продайте");
    expect(html).not.toContain("рекомендуем");
  });
});
