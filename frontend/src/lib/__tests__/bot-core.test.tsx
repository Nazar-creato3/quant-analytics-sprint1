import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { BotPaperCard } from "@/components/account/BotPaperCard";

describe("paper bot card", () => {
  it("carries an empty cost config and stays off live", () => {
    const html = renderToStaticMarkup(<BotPaperCard />);
    expect(html).toContain("Бумажный бот");
    expect(html).toContain("Создать бумажного бота");
    expect(html).toContain("Комиссия: нет данных");
    expect(html).toContain('data-paper-days="30"');
    expect(html).toContain("Реальный режим выключен");
    expect(html).not.toContain("купите");
    expect(html).not.toContain("продайте");
  });
});
