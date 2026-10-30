import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { OpsStatusCard } from "@/components/admin/OpsStatusCard";

describe("ops perf section", () => {
  it("exposes SLO, drills, and perf without forbidden phrases", () => {
    const html = renderToStaticMarkup(<OpsStatusCard />);
    expect(html).toContain("SLO");
    expect(html).toContain("Drills");
    expect(html).toContain("Perf");
    expect(html).toContain("data-provider");
    expect(html).toContain("Запустить бюджет");
    expect(html).not.toContain("купите");
    expect(html).not.toContain("продайте");
    expect(html).not.toContain("рекомендуем");
  });
});
