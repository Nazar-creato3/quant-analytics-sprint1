import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import AccuracySlotPage from "@/app/site/accuracy/page";

describe("accuracy page", () => {
  it("does not publish a forecast accuracy number", () => {
    const html = renderToStaticMarkup(<AccuracySlotPage />);
    expect(html).toContain("Опубликованная точность: нет данных.");
    expect(html).toContain("Слабые периоды: нет данных.");
    expect(html).not.toContain("купите");
    expect(html).not.toContain("%");
  });
});
