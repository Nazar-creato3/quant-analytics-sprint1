import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { SubscriptionCard } from "@/components/account/SubscriptionCard";

describe("subscription card", () => {
  it("shows an unset price", () => {
    const html = renderToStaticMarkup(<SubscriptionCard />);
    expect(html).toContain("Подписка");
    expect(html).toContain("Цена: нет данных");
    expect(html).not.toContain("купите");
    expect(html).not.toContain("продайте");
  });
});
