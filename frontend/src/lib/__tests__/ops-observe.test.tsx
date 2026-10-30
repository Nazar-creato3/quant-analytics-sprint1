import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { OpsStatusCard } from "@/components/admin/OpsStatusCard";

describe("ops status card", () => {
  it("shows unset backup and infrastructure payment", () => {
    const html = renderToStaticMarkup(<OpsStatusCard />);
    expect(html).toContain("Наблюдаемость");
    expect(html).toContain("Бэкап: нет данных");
    expect(html).toContain("Оплата инфраструктуры: нет данных");
    expect(html).not.toContain("купите");
    expect(html).not.toContain("продайте");
  });
});
