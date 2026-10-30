"use client";

import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { marketApi, type FundamentalsSnapshot } from "@/lib/api";
import { useActiveTicker } from "@/contexts/ActiveTickerContext";
import { formatFmpReturnOn, formatFmpShare } from "@/lib/fmp-percent";

function fmt(value: number | null | undefined, digits = 2): string {
  if (value == null || !Number.isFinite(value)) return "—";
  const abs = Math.abs(value);
  if (abs >= 1e12) return `${(value / 1e12).toFixed(2)} трлн`;
  if (abs >= 1e9) return `${(value / 1e9).toFixed(2)} млрд`;
  if (abs >= 1e6) return `${(value / 1e6).toFixed(2)} млн`;
  return value.toFixed(digits);
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-2 border-b border-terminal-border/40 py-0.5 min-w-0">
      <span className="text-[9px] uppercase text-terminal-muted shrink-0">{label}</span>
      <span className="text-[11px] font-mono text-terminal-text truncate">{value}</span>
    </div>
  );
}

function Group({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="min-w-0">
      <h3 className="text-[9px] uppercase tracking-wide text-terminal-accent mb-1">{title}</h3>
      <div className="space-y-0">{children}</div>
    </section>
  );
}

function hasCoverage(data: FundamentalsSnapshot | undefined): boolean {
  if (!data) return false;
  return Boolean(
    data.pe_ratio != null ||
      data.market_cap != null ||
      data.roe != null ||
      data.revenue != null ||
      data.gross_margin != null,
  );
}

export function TerminalFundamentalsSnapshot() {
  const { activeTicker } = useActiveTicker();
  const symbol = activeTicker;

  const { data, isLoading, isError } = useQuery({
    queryKey: ["fundamentals-snapshot", symbol],
    queryFn: () => marketApi.fundamentalsSnapshot(symbol),
    staleTime: 120_000,
    enabled: !!symbol,
  });

  return (
    <div className="p-2 space-y-2">
      <div className="flex items-baseline justify-between gap-2">
        <p className="text-[11px] font-mono text-terminal-text truncate">
          {data?.short_name ?? symbol}
          {data?.exchange ? <span className="text-terminal-muted"> · {data.exchange}</span> : null}
        </p>
        <p className="text-[9px] text-terminal-muted shrink-0">
          {data?.sector ?? "—"}
          {data?.industry ? ` · ${data.industry}` : ""}
        </p>
      </div>

      {isLoading && <p className="text-[11px] text-terminal-muted">Загрузка…</p>}
      {isError && (
        <p className="text-[11px] text-terminal-muted">Показатели недоступны.</p>
      )}
      {!isLoading && data && !hasCoverage(data) && (
        <p className="text-[11px] text-terminal-muted">Нет данных по этому инструменту.</p>
      )}

      <div className="grid grid-cols-2 xl:grid-cols-4 gap-3">
        <Group title="Оценка">
          <Metric label="Капитализация" value={fmt(data?.market_cap, 0)} />
          <Metric label="Стоимость компании" value={fmt(data?.enterprise_value, 0)} />
          <Metric label="Цена / прибыль" value={fmt(data?.pe_ratio)} />
          <Metric label="Цена / капитал" value={fmt(data?.price_to_book)} />
          <Metric label="Цена / выручка" value={fmt(data?.price_to_sales)} />
          <Metric label="Рост" value={fmt(data?.peg)} />
          <Metric label="Стоимость / прибыль" value={fmt(data?.ev_to_ebitda)} />
        </Group>
        <Group title="Прибыльность">
          <Metric label="Валовая маржа" value={formatFmpShare(data?.gross_margin)} />
          <Metric label="Операционная маржа" value={formatFmpShare(data?.operating_margin)} />
          <Metric label="Чистая маржа" value={formatFmpShare(data?.net_profit_margin ?? data?.profit_margin)} />
          <Metric label="Отдача капитала" value={formatFmpReturnOn(data?.roe)} />
          <Metric label="Отдача активов" value={formatFmpReturnOn(data?.roa)} />
          <Metric label="Отдача вложений" value={formatFmpReturnOn(data?.roic)} />
          <Metric label="Прибыль на акцию" value={fmt(data?.eps)} />
        </Group>
        <Group title="Баланс">
          <Metric label="Долг / капитал" value={fmt(data?.debt_to_equity)} />
          <Metric label="Текущая ликвидность" value={fmt(data?.current_ratio)} />
          <Metric label="Быстрая ликвидность" value={fmt(data?.quick_ratio)} />
          <Metric label="Покрытие процентов" value={fmt(data?.interest_coverage)} />
          <Metric label="Поток на акцию" value={fmt(data?.fcf_per_share)} />
          <Metric label="Дивиденды" value={formatFmpShare(data?.dividend_yield)} />
          <Metric label="Доля выплат" value={formatFmpShare(data?.payout_ratio)} />
        </Group>
        <Group title="Масштаб">
          <Metric label="Выручка" value={fmt(data?.revenue, 0)} />
          <Metric label="Чистая прибыль" value={fmt(data?.net_income, 0)} />
          <Metric label="Чувствительность" value={fmt(data?.beta)} />
        </Group>
      </div>
    </div>
  );
}
