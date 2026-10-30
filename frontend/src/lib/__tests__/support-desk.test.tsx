import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import SupportPage from "@/app/support/page";
import SupportStatusPage from "@/app/support/status/page";

describe("support pages", () => {
  it("does not send mail or invent a known issue", () => {
    const html = renderToStaticMarkup(
      <div>
        <SupportPage />
        <SupportStatusPage />
      </div>,
    );
    expect(html).toContain("Сообщить о проблеме");
    expect(html).toContain("Уведомление Slack: нет данных");
    expect(html).toContain("Известные проблемы: нет данных");
    expect(html).not.toContain("купите");
    expect(html).not.toContain("рекомендуем");
    expect(html).not.toContain("@");
  });
});
