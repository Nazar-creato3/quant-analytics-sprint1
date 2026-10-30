type TargetBook = {
  status?: string;
  reason?: string;
  method?: string;
  target_source?: string;
  weights?: Record<string, string> | null;
  sum_weights?: string;
  tax?: { rate?: string | null };
};

function goalSource(raw: string | undefined): string {
  if (!raw || raw === "user") return "задана вами";
  return "нет данных";
}

function goalStatus(raw: string | undefined): string {
  if (raw === "ok") return "готово";
  if (!raw) return "нет данных";
  return "нет данных";
}

export function TargetBookPanel({ book }: { book?: TargetBook | null }) {
  const weights = book?.weights && typeof book.weights === "object" ? book.weights : null;
  const tickers = weights ? Object.keys(weights).sort() : [];
  const taxRate = book?.tax?.rate ? String(book.tax.rate) : "нет данных";
  return (
    <section className="cockpit-panel p-4 text-xs space-y-1" data-testid="target-book">
      <p className="uppercase tracking-wide text-qa-muted">Целевая структура</p>
      <p data-testid="target-source">Источник цели: {goalSource(book?.target_source)}</p>
      <p data-testid="target-status">Статус: {goalStatus(book?.status)}</p>
      {book?.reason ? <p>{book.reason}</p> : null}
      {tickers.length === 0 ? <p data-testid="target-weights">Доли: нет данных</p> : null}
      {tickers.map((ticker) => (
        <p key={ticker} data-testid="target-weight">
          {ticker} {String(weights?.[ticker] ?? "нет данных")}
        </p>
      ))}
      {book?.sum_weights ? <p data-testid="target-sum">Сумма долей: {book.sum_weights}</p> : null}
      <p data-testid="target-tax">Налог: {taxRate}</p>
    </section>
  );
}
