"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { cockpitApi, marketApi } from "@/lib/api";
import { isEquitySymbol } from "./direct-deals-tabs";

function fmtYield(value: unknown): string {
  if (value == null) return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return `${(n < 1 ? n * 100 : n).toFixed(2)}%`;
}

interface DirectDealsDividendsTabProps {
  ticker: string;
}

export function DirectDealsDividendsTab({ ticker }: DirectDealsDividendsTabProps) {
  const isEquity = isEquitySymbol(ticker);

  const { data: quote, isLoading: quoteLoading } = useQuery({
    queryKey: ["direct-deals-div-quote", ticker],
    queryFn: () => marketApi.getQuote(ticker),
    enabled: isEquity,
    staleTime: 60_000,
  });

  const { data: cockpit, isLoading: cockpitLoading } = useQuery({
    queryKey: ["direct-deals-div-cockpit", ticker],
    queryFn: () => cockpitApi.get(ticker),
    enabled: isEquity,
    staleTime: 60_000,
  });

  const fundamentals = useMemo(() => {
    const quoteRecord = (quote ?? {}) as Record<string, unknown>;
    const meta = (cockpit?.metadata ?? {}) as Record<string, unknown>;
    return {
      ...((quoteRecord.fundamentals ?? {}) as Record<string, unknown>),
      ...((meta.fundamentals ?? meta.fundamental ?? {}) as Record<string, unknown>),
    };
  }, [quote, cockpit]);

  if (!isEquity) {
    return (
      <p className="text-xs text-qa-muted text-center py-10">
        Дивиденды доступны только для акций
      </p>
    );
  }

  if (quoteLoading || cockpitLoading) {
    return (
      <div className="flex items-center justify-center gap-2 py-12 text-xs text-qa-muted">
        <Loader2 size={14} className="animate-spin" /> Загрузка…
      </div>
    );
  }

  const divYield = fundamentals.dividend_yield ?? fundamentals.dividendYield;
  const divRate = fundamentals.dividend_rate ?? fundamentals.dividendRate;
  const exDate = fundamentals.ex_dividend_date ?? fundamentals.exDividendDate;
  const payDate = fundamentals.dividend_date ?? fundamentals.dividendDate;
  const hasData = divYield != null || divRate != null;

  if (!hasData) {
    return (
      <div className="p-6 text-center space-y-2">
        <p className="text-sm text-qa-text">Данные по дивидендам недоступны</p>
        <p className="text-xs text-qa-muted">
          Провайдер котировок не вернул dividend yield для {ticker}
        </p>
      </div>
    );
  }

  return (
    <div className="p-4 grid grid-cols-2 sm:grid-cols-3 gap-3">
      <div className="rounded border border-terminal-up/30 bg-terminal-up/5 px-3 py-3">
        <div className="text-[9px] uppercase text-qa-muted mb-1">Дивидендная доходность</div>
        <div className="text-lg font-bold text-terminal-up tabular-nums">{fmtYield(divYield)}</div>
      </div>
      <div className="rounded border border-qa-border bg-qa-panel-secondary/50 px-3 py-3">
        <div className="text-[9px] uppercase text-qa-muted mb-1">Ставка</div>
        <div className="text-lg font-bold text-qa-text tabular-nums">
          {divRate != null ? `$${Number(divRate).toFixed(2)}` : "—"}
        </div>
      </div>
      <div className="rounded border border-qa-border bg-qa-panel-secondary/50 px-3 py-3">
        <div className="text-[9px] uppercase text-qa-muted mb-1">Дата отсечки</div>
        <div className="text-sm font-mono text-qa-text">{exDate ? String(exDate) : "—"}</div>
      </div>
      <div className="rounded border border-qa-border bg-qa-panel-secondary/50 px-3 py-3">
        <div className="text-[9px] uppercase text-qa-muted mb-1">Дата выплаты</div>
        <div className="text-sm font-mono text-qa-text">{payDate ? String(payDate) : "—"}</div>
      </div>
    </div>
  );
}
