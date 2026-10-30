"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertCircle, ExternalLink, Loader2 } from "lucide-react";
import { regulatoryApi } from "@/lib/api";

function fmtDate(value: unknown): string {
  if (typeof value !== "string" || !value) return "—";
  try {
    return new Intl.DateTimeFormat("ru-RU", {
      timeZone: "Europe/Moscow",
      year: "numeric",
      month: "short",
      day: "2-digit",
    }).format(new Date(value));
  } catch {
    return value;
  }
}

function fmtNum(value: unknown): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return n.toLocaleString("en-US", { maximumFractionDigits: 0 });
}

interface DirectDealsRegulatoryTabProps {
  ticker: string;
}

export function DirectDealsRegulatoryTab({ ticker }: DirectDealsRegulatoryTabProps) {
  const {
    data: secResult,
    isLoading: secLoading,
    error: secError,
  } = useQuery({
    queryKey: ["direct-deals-regulatory-sec", ticker],
    queryFn: () => regulatoryApi.getSecFilings(ticker, { limit: 15 }),
    staleTime: 120_000,
    retry: 1,
  });

  const {
    data: finraResult,
    isLoading: finraLoading,
    error: finraError,
  } = useQuery({
    queryKey: ["direct-deals-regulatory-finra", ticker],
    queryFn: () => regulatoryApi.getFinraShortInterest(ticker, { limit: 6 }),
    staleTime: 120_000,
    retry: 1,
  });

  const secDisabled = secResult && !secResult.success && secResult.error_code === "SOURCE_DISABLED";
  const finraDisabled = finraResult && !finraResult.success && finraResult.error_code === "SOURCE_DISABLED";
  const sourceOff = Boolean(secDisabled || finraDisabled);

  const secFilings = (secResult?.data?.filings ?? []) as Array<Record<string, unknown>>;
  const finraRecords = (finraResult?.data?.records ?? []) as Array<Record<string, unknown>>;

  if (secLoading && finraLoading && !secResult && !finraResult) {
    return (
      <div className="flex items-center justify-center gap-2 py-12 text-xs text-qa-muted">
        <Loader2 size={14} className="animate-spin" /> Загрузка регуляторных данных…
      </div>
    );
  }

  if (sourceOff) {
    return (
      <div className="p-6 flex flex-col items-center justify-center gap-2 text-center min-h-[240px]">
        <AlertCircle size={20} className="text-qa-muted" />
        <p className="text-sm text-qa-text">Регуляторные данные временно недоступны</p>
        <p className="text-[11px] text-qa-muted max-w-sm">
          SEC-отчётность и FINRA short interest отключены администратором. Остальные разделы платформы работают
          без изменений.
        </p>
      </div>
    );
  }

  const secUnavailable =
    (secResult && !secResult.success) || Boolean(secError);
  const finraUnavailable =
    (finraResult && !finraResult.success) || Boolean(finraError);

  return (
    <div className="p-4 space-y-6 overflow-y-auto min-h-0 h-full">
      <section>
        <h3 className="text-[10px] uppercase text-qa-muted mb-2">SEC — последние отчёты</h3>
        {secUnavailable ? (
          <p className="text-xs text-qa-muted rounded border border-qa-border bg-qa-panel-secondary/50 px-3 py-2">
            {secResult?.error ?? "Данные SEC временно недоступны"}
          </p>
        ) : secFilings.length === 0 ? (
          <p className="text-xs text-qa-muted">Отчёты не найдены для {ticker.toUpperCase()}</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-[9px] uppercase text-qa-muted border-b border-qa-border">
                  <th className="text-left py-1.5 pr-2">Форма</th>
                  <th className="text-left py-1.5 pr-2">Дата подачи</th>
                  <th className="text-left py-1.5">Ссылка</th>
                </tr>
              </thead>
              <tbody>
                {secFilings.map((row, idx) => (
                  <tr key={`${row.form_type}-${row.filing_date}-${idx}`} className="border-b border-qa-border/50">
                    <td className="py-1.5 pr-2 font-mono">{String(row.form_type ?? "—")}</td>
                    <td className="py-1.5 pr-2 tabular-nums">{fmtDate(row.filing_date)}</td>
                    <td className="py-1.5">
                      {row.link ? (
                        <a
                          href={String(row.link)}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 text-terminal-accent hover:underline"
                        >
                          SEC <ExternalLink size={10} />
                        </a>
                      ) : (
                        "—"
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section>
        <h3 className="text-[10px] uppercase text-qa-muted mb-2">FINRA — short interest</h3>
        {finraUnavailable ? (
          <p className="text-xs text-qa-muted rounded border border-qa-border bg-qa-panel-secondary/50 px-3 py-2">
            {finraResult?.error ?? "Данные FINRA временно недоступны"}
          </p>
        ) : finraRecords.length === 0 ? (
          <p className="text-xs text-qa-muted">Нет данных о коротких позициях по {ticker.toUpperCase()}</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-[9px] uppercase text-qa-muted border-b border-qa-border">
                  <th className="text-left py-1.5 pr-2">Дата расчёта</th>
                  <th className="text-right py-1.5 pr-2">Короткие позиции</th>
                  <th className="text-right py-1.5 pr-2">Ранее</th>
                  <th className="text-right py-1.5">Дней на закрытие</th>
                </tr>
              </thead>
              <tbody>
                {finraRecords.map((row, idx) => (
                  <tr key={`${row.settlement_date}-${idx}`} className="border-b border-qa-border/50">
                    <td className="py-1.5 pr-2 tabular-nums">{fmtDate(row.settlement_date)}</td>
                    <td className="py-1.5 pr-2 text-right font-mono tabular-nums">
                      {fmtNum(row.current_short_position)}
                    </td>
                    <td className="py-1.5 pr-2 text-right font-mono tabular-nums">
                      {fmtNum(row.previous_short_position)}
                    </td>
                    <td className="py-1.5 text-right font-mono tabular-nums">
                      {fmtNum(row.days_to_cover)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
