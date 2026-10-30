import { botPaperConfig, botPaperLines } from "@/lib/bot-core";

export function BotPaperCard() {
  const lines = botPaperLines();
  return (
    <section aria-labelledby="bot-paper-title" className="rounded-xl border border-qa-border p-3 text-sm">
      <h2 id="bot-paper-title" className="font-medium">
        {lines[0]}
      </h2>
      <p className="mt-1 text-xs text-qa-muted">{lines[1]}</p>
      <p className="mt-1 text-xs text-qa-muted">{lines[2]}</p>
      <p className="mt-1 text-xs text-qa-muted">{lines[3]}</p>
      <p className="mt-1 text-xs text-qa-muted">{lines[4]}</p>
      <button
        type="button"
        className="mt-2 text-xs"
        data-paper-days={botPaperConfig.paperDays}
        data-commission={botPaperConfig.commission}
        data-slippage={botPaperConfig.slippage}
      >
        Создать бумажного бота
      </button>
    </section>
  );
}
