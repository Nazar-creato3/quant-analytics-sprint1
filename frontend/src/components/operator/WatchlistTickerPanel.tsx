"use client";

import { useQuery } from "@tanstack/react-query";
import { clsx } from "clsx";
import { format, parseISO } from "date-fns";
import { ExternalLink, Newspaper } from "lucide-react";
import { cockpitApi, marketApi, newsApi } from "@/lib/api";
import { formatInstrumentPrice } from "@/lib/instrument-price-format";
import { Spinner } from "@/components/ui";
import { MainChartPanel } from "@/components/operator/MainChartPanel";
import type { AssetCockpitData } from "@/types";

function formatLargeNumber(value: unknown): string {
  if (value == null || value === "") return "нет данных";
  const n = Number(value);
  if (!Number.isFinite(n)) return "нет данных";
  const sign = n < 0 ? "-" : "";
  const abs = Math.abs(n);
  if (abs >= 1e12) return `${sign}${(abs / 1e12).toFixed(2)} трлн`;
  if (abs >= 1e9) return `${sign}${(abs / 1e9).toFixed(2)} млрд`;
  if (abs >= 1e6) return `${sign}${(abs / 1e6).toFixed(2)} млн`;
  if (abs < 1 && n !== 0) return `${(n * 100).toFixed(2)}%`;
  return n.toFixed(2);
}

function StatCard({
  label,
  value,
  accent,
}: {
  label: string;
  value: React.ReactNode;
  accent?: "emerald" | "amber" | "terminal" | "sky";
}) {
  const accentClass =
    accent === "emerald"
      ? "border-terminal-up/40"
      : accent === "amber" || accent === "terminal" || accent === "sky"
      ? "border-terminal-accent/40"
      : "border-terminal-accent/30";

  return (
    <div className={clsx("rounded-xl border bg-cockpit-panel-raised p-4", accentClass)}>
      <p className="text-xs uppercase tracking-wide text-qa-muted mb-2">{label}</p>
      <p className="text-lg font-bold text-white tabular-nums leading-tight">{value}</p>
    </div>
  );
}

export function WatchlistTickerPanel({ ticker, className }: { ticker: string; className?: string }) {
  const { data: cockpit, isLoading: cockpitLoading } = useQuery<AssetCockpitData>({
    queryKey: ["watchlist-cockpit", ticker],
    queryFn: () => cockpitApi.get(ticker),
    staleTime: 30_000,
    refetchInterval: 30_000,
  });

  const { data: quote, isLoading: quoteLoading } = useQuery({
    queryKey: ["watchlist-quote", ticker],
    queryFn: () => marketApi.getQuote(ticker),
    staleTime: 15_000,
    refetchInterval: 15_000,
  });

  const { data: newsPage, isLoading: newsLoading } = useQuery({
    queryKey: ["watchlist-news", ticker],
    queryFn: () => newsApi.list({ ticker, page: 1, page_size: 8 }),
    staleTime: 60_000,
  });

  const meta = (cockpit?.metadata ?? {}) as Record<string, unknown>;
  const quoteRecord = (quote ?? {}) as Record<string, unknown>;
  const fundamentals = {
    ...((quoteRecord.fundamentals ?? {}) as Record<string, unknown>),
    ...((meta.fundamentals ?? meta.fundamental ?? {}) as Record<string, unknown>),
  };
  const technical = {
    ...((quoteRecord.technical ?? quoteRecord.technicals ?? {}) as Record<string, unknown>),
    ...((meta.technical ?? meta.technicals ?? {}) as Record<string, unknown>),
  };

  const isLoading = cockpitLoading || quoteLoading;
  const price = cockpit?.price ?? (quote?.last as number | undefined) ?? (quote?.price as number | undefined);
  const changePct = quote?.change_percent ?? quote?.changePercent;
  const volume = quote?.volume ?? meta.volume;
  const spreadBps = cockpit?.spread_bps;
  const dayLow = cockpit?.price_range?.period_low;
  const dayHigh = cockpit?.price_range?.period_high;
  const vol = cockpit?.volatility_bands?.realized_vol;
  const rsi = technical.rsi ?? technical.RSI;
  const macd = technical.macd ?? technical.MACD;
  const atr = technical.atr ?? technical.ATR;
  const avgVolume = technical.avg_volume ?? technical.averageVolume ?? fundamentals.averageVolume;

  const news = (newsPage?.items ?? []).filter(a => !a.is_demo);

  return (
    <div className={clsx("cockpit-panel flex flex-col min-h-0 overflow-hidden", className)}>
      <div className="cockpit-panel-header px-4 py-3">
        <div>
          <span className="text-lg font-bold font-mono normal-case tracking-normal">{ticker}</span>
          {cockpit?.regime_label && (
            <span className="ml-2 text-[11px] font-normal normal-case text-terminal-accent capitalize">
              {cockpit.regime_label.replace(/_/g, " ")}
            </span>
          )}
        </div>
        <div className="text-right">
          <span className="text-xl font-bold font-mono text-qa-text normal-case tracking-normal">
            {price != null
              ? formatInstrumentPrice(
                  ticker,
                  Number(price),
                  (quoteRecord.currency as string | undefined),
                )
              : isLoading
                ? "…"
                : "нет данных"}
          </span>
          {changePct != null && (
            <p className={clsx(
              "text-xs font-semibold tabular-nums mt-0.5",
              Number(changePct) >= 0 ? "text-terminal-up" : "text-terminal-down",
            )}>
              {Number(changePct) >= 0 ? "+" : ""}{Number(changePct).toFixed(2)}%
            </p>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-5">
        {isLoading && !cockpit ? (
          <div className="flex justify-center py-16">
            <Spinner />
          </div>
        ) : (
          <>
            <section className="rounded-xl overflow-hidden border border-cockpit-border bg-cockpit-bg/40">
              <MainChartPanel ticker={ticker} fixedHeight={300} className="!h-auto" />
            </section>

            <section>
              <h3 className="section-title mb-3">
                Показатели
              </h3>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                <StatCard label="Капитализация" value={formatLargeNumber(fundamentals.market_cap ?? fundamentals.marketCap)} accent="emerald" />
                <StatCard label="Цена / прибыль" value={formatLargeNumber(fundamentals.pe_ratio ?? fundamentals.peRatio ?? fundamentals.trailingPE)} accent="emerald" />
                <StatCard label="Прибыль на акцию" value={formatLargeNumber(fundamentals.eps ?? fundamentals.trailingEps)} accent="emerald" />
                <StatCard label="Дивиденды" value={formatLargeNumber(fundamentals.dividend_yield ?? fundamentals.dividendYield)} accent="emerald" />
                <StatCard label="Отдача капитала" value={formatLargeNumber(fundamentals.roe ?? fundamentals.returnOnEquity)} accent="emerald" />
                <StatCard label="Отдача активов" value={formatLargeNumber(fundamentals.roa ?? fundamentals.returnOnAssets)} accent="emerald" />
              </div>
            </section>

            <section>
              <h3 className="text-xs font-bold uppercase tracking-wider text-terminal-accent mb-3">
                Технические
              </h3>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                <StatCard label="Чувствительность" value={formatLargeNumber(technical.beta ?? fundamentals.beta)} accent="amber" />
                <StatCard
                  label="Диапазон года"
                  value={
                    technical.week52_low != null && technical.week52_high != null
                      ? `${Number(technical.week52_low).toFixed(0)} – ${Number(technical.week52_high).toFixed(0)}`
                      : formatLargeNumber(technical.fiftyTwoWeekRange ?? fundamentals.fiftyTwoWeekRange)
                  }
                  accent="amber"
                />
                <StatCard label="Сила" value={formatLargeNumber(rsi)} accent="amber" />
                <StatCard label="Схождение" value={formatLargeNumber(macd)} accent="amber" />
                <StatCard label="Ход" value={formatLargeNumber(atr)} accent="amber" />
                <StatCard label="Средний объём" value={formatLargeNumber(avgVolume ?? volume)} accent="amber" />
              </div>
            </section>

            <section>
              <h3 className="text-xs font-bold uppercase tracking-wider text-terminal-accent mb-3">
                Рыночные показатели
              </h3>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <StatCard label="Спред" value={spreadBps != null ? `${spreadBps.toFixed(1)} б.п.` : "нет данных"} accent="terminal" />
                <StatCard label="Волатильность" value={vol != null ? `${(vol * 100).toFixed(1)}%` : "нет данных"} accent="terminal" />
                <StatCard label="Режим" value={cockpit?.regime_label ?? "нет данных"} accent="terminal" />
                <StatCard
                  label="Дневной диапазон"
                  value={
                    dayLow != null && dayHigh != null
                      ? `${dayLow.toFixed(2)} – ${dayHigh.toFixed(2)}`
                      : "нет данных"
                  }
                  accent="terminal"
                />
              </div>
            </section>

            <section>
              <div className="flex items-center gap-2 mb-3">
                <Newspaper size={14} className="text-terminal-accent" />
                <h3 className="text-xs font-bold uppercase tracking-wider text-terminal-accent">
                  Recent News · {ticker}
                </h3>
              </div>
              {newsLoading ? (
                <div className="flex justify-center py-8"><Spinner size={20} /></div>
              ) : news.length === 0 ? (
                <p className="text-sm text-qa-muted rounded-xl border border-cockpit-border bg-cockpit-panel-raised p-4">
                  Нет свежих новостей по {ticker}. Запустите news ingestion в настройках.
                </p>
              ) : (
                <div className="space-y-3">
                  {news.map(article => (
                    <a
                      key={article.id}
                      href={article.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="block rounded-xl border border-cockpit-border bg-cockpit-panel-raised p-4 hover:border-cockpit-border-strong transition-colors group"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <p className="text-sm font-semibold text-qa-text leading-snug group-hover:text-white">
                          {article.title}
                        </p>
                        <ExternalLink size={14} className="text-qa-muted shrink-0 mt-0.5 group-hover:text-terminal-accent" />
                      </div>
                      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-2 text-[11px] text-qa-muted">
                        <span>{article.source}</span>
                        <span>{format(parseISO(article.published_at), "dd MMM yyyy, HH:mm")}</span>
                        {article.sentiment_label && (
                          <span className={clsx(
                            "px-1.5 py-0.5 rounded text-[10px] uppercase font-semibold",
                            article.sentiment_label === "positive" && "bg-qa-success-bg text-terminal-up",
                            article.sentiment_label === "negative" && "bg-qa-danger-bg text-terminal-down",
                            article.sentiment_label === "neutral" && "bg-qa-panel-secondary text-qa-muted",
                          )}>
                            {article.sentiment_label}
                          </span>
                        )}
                      </div>
                    </a>
                  ))}
                </div>
              )}
            </section>

            {cockpit?.why_so?.headline && (
              <section className="rounded-xl border border-cockpit-border bg-cockpit-panel-raised p-4">
                <p className="text-[11px] uppercase text-qa-muted mb-2">Расчёты</p>
                <p className="text-sm text-qa-text leading-relaxed">{cockpit.why_so.headline}</p>
              </section>
            )}
          </>
        )}
      </div>
    </div>
  );
}
