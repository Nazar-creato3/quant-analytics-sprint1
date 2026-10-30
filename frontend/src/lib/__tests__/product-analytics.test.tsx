import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { AnalyticsNote } from "@/components/site/AnalyticsNote";
import { trackBody, trackClientEvent } from "@/lib/product-analytics";

describe("product analytics note", () => {
  it("keeps tracking off until consent text exists", () => {
    const html = renderToStaticMarkup(<AnalyticsNote />);
    expect(html).toContain("текст согласия нет данных");
    expect(html).toContain("не отслеживать");
    expect(html).toContain('data-analytics-status="dnt"');
    expect(html).not.toContain("купите");
    expect(html).not.toContain("рекомендуем");
    const body = trackBody({
      name: "user_return",
      subject: "site",
      properties: {},
      consent: false,
      doNotTrack: true,
    });
    expect(body.do_not_track).toBe(true);
    expect(body.consent).toBe(false);
    expect(body).not.toHaveProperty("email");
  });

  it("does not put email into the payload", async () => {
    const body = trackBody({
      name: "risk_view",
      subject: "anon",
      properties: {},
      consent: false,
      doNotTrack: true,
    });
    expect(JSON.stringify(body)).not.toContain("@");
    expect(body.do_not_track).toBe(true);
    const html = renderToStaticMarkup(<AnalyticsNote />);
    expect(html).toMatch(/ожидает текста|нет данных/);
    expect(html).not.toContain("купите");
    const rejected = await trackClientEvent("registration", { email: "a@b.c" });
    expect(rejected.status).toBe("rejected");
    expect(JSON.stringify(rejected)).not.toContain("@");
  });
});
