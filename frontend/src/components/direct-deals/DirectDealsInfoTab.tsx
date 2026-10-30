"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { cockpitApi, directDealsApi, marketApi } from "@/lib/api";
import { useEffectiveWatchlist } from "@/hooks/useEffectiveWatchlist";

function fmtLarge(value: unknown): string {
  if (value == null || value === "") return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return String(value);
  if (n >= 1e12) return `$${(n / 1e12).toFixed(2)}T`;
  if (n >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(2)}M`;
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function fmtPrice(value: unknown): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  if (n >= 1000) return n.toFixed(2);
  if (n >= 1) return n.toFixed(4);
  return n.toFixed(6);
}

function formatMsk(iso: unknown): string {
  if (typeof iso !== "string" || !iso) return "—";
  try {
    return new Intl.DateTimeFormat("ru-RU", {
      timeZone: "Europe/Moscow",
      day: "2-digit",
      month: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    }).format(new Date(iso));
  } catch {
    return "—";
  }
}

interface DirectDealsInfoTabProps {
  ticker: string;
}

export function DirectDealsInfoTab({ ticker }: DirectDealsInfoTabProps) {
  const { entries } = useEffectiveWatchlist();
  const entry = useMemo(
    () => entries.find((e) => e.symbol.toUpperCase() === ticker.toUpperCase()),
    [entries, ticker],
  );

  const { data: quote, isLoading: quoteLoading } = useQuery({
    queryKey: ["direct-deals-info-quote", ticker],
    // Soft-budgeted enrich for fundamentals/technicals; price still returns if enrich times out.
    queryFn: () => marketApi.getQuote(ticker, { enrich: true }),
    staleTime: 30_000,
    retry: 1,
  });

  const { data: cockpit, isLoading: cockpitLoading } = useQuery({
    queryKey: ["direct-deals-info-cockpit", ticker],
    queryFn: () => cockpitApi.get(ticker),
    staleTime: 60_000,
    retry: 1,
  });

  const { data: symbols } = useQuery({
    queryKey: ["direct-deals-symbols-info", ticker],
    queryFn: () => directDealsApi.symbols({ q: ticker, limit: 5 }),
    staleTime: 300_000,
  });

  const symbolMeta = useMemo(
    () => symbols?.find((s) => s.symbol.toUpperCase() === ticker.toUpperCase()),
    [symbols, ticker],
  );

  const isLoading = quoteLoading && !quote;
  const quoteRecord = (quote ?? {}) as Record<string, unknown>;
  const meta = (cockpit?.metadata ?? {}) as Record<string, unknown>;
  const fundamentals = {
    ...((quoteRecord.fundamentals ?? {}) as Record<string, unknown>),
    ...((meta.fundamentals ?? meta.fundamental ?? {}) as Record<string, unknown>),
  };
  const technical = {
    ...((quoteRecord.technical ?? quoteRecord.technicals ?? {}) as Record<string, unknown>),
    ...((meta.technical ?? meta.technicals ?? {}) as Record<string, unknown>),
  };

  const description =
    (fundamentals.description as string | undefined) ||
    (meta.description as string | undefined) ||
    symbolMeta?.name ||
    entry?.label_ru ||
    entry?.label ||
    null;

  if (isLoading && !quote && cockpitLoading && !cockpit) {
    return (
      <div className="flex items-center justify-center gap-2 py-12 text-xs text-qa-muted">
        <Loader2 size={14} className="animate-spin" /> Загрузка…
      </div>
    );
  }

  const bid = quoteRecord.bid;
  const ask = quoteRecord.ask;
  const spreadBps =
    bid != null && ask != null && Number(bid) > 0 && Number(ask) > 0
      ? (((Number(ask) - Number(bid)) / ((Number(ask) + Number(bid)) / 2)) * 10_000).toFixed(2)
      : null;

  const rows: { label: string; value: string }[] = [
    { label: "Тикер", value: ticker.toUpperCase() },
    {
      label: "Название",
      value: symbolMeta?.name ?? entry?.label_ru ?? entry?.label ?? "—",
    },
    { label: "Сектор", value: entry?.sector ?? (fundamentals.sector as string) ?? "—" },
    {
      label: "Рынок",
      value:
        symbolMeta?.exchange ??
        entry?.market ??
        (quoteRecord.exchange as string) ??
        (quoteRecord.market as string) ??
        "—",
    },
    { label: "Класс", value: symbolMeta?.asset_class ?? entry?.category ?? "—" },
    { label: "Источник котировки", value: (quoteRecord.source as string) ?? "—" },
    { label: "Последняя цена", value: fmtPrice(quoteRecord.price ?? quoteRecord.last) },
    { label: "Bid / Ask", value: bid != null && ask != null ? `${fmtPrice(bid)} / ${fmtPrice(ask)}` : "—" },
    { label: "Spread (bps)", value: spreadBps ?? "—" },
    {
      label: "Изменение %",
      value:
        quoteRecord.change_pct != null
          ? `${Number(quoteRecord.change_pct).toFixed(2)}%`
          : "—",
    },
    {
      label: "Объём",
      value: fmtLarge(quoteRecord.volume ?? quoteRecord.volume_24h),
    },
    {
      label: "Капитализация",
      value: fmtLarge(fundamentals.market_cap ?? fundamentals.marketCap),
    },
    {
      label: "P/E",
      value: fundamentals.pe_ratio != null ? String(fundamentals.pe_ratio) : "—",
    },
    {
      label: "52W диапазон",
      value:
        technical.week52_low != null && technical.week52_high != null
          ? `$${Number(technical.week52_low).toFixed(2)} – $${Number(technical.week52_high).toFixed(2)}`
          : "—",
    },
    {
      label: "Beta",
      value: fundamentals.beta != null ? String(fundamentals.beta) : "—",
    },
    { label: "Обновлено (MSK)", value: formatMsk(quoteRecord.timestamp ?? quoteRecord.as_of) },
  ];

  return (
    <div className="p-4 space-y-4 overflow-y-auto min-h-0 h-full">
      {description && (
        <div>
          <h3 className="text-[10px] uppercase text-qa-muted mb-1">Описание</h3>
          <p className="text-xs text-qa-text leading-relaxed">{description}</p>
        </div>
      )}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        {rows.map((row) => (
          <div
            key={row.label}
            className="rounded border border-qa-border bg-qa-panel-secondary/50 px-3 py-2"
          >
            <div className="text-[9px] uppercase text-qa-muted mb-0.5">{row.label}</div>
            <div className="text-sm font-mono text-qa-text tabular-nums break-all">{row.value}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
