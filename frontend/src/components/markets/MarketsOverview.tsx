"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { clsx } from "clsx";
import Link from "next/link";
import { marketApi } from "@/lib/api";
import { CrossActions } from "@/components/shared/CrossActions";

type QuoteRow = {
  symbol: string;
  name?: string;
  price?: number | null;
  change_pct?: number | null;
  volume?: number | null;
  prev_close?: number | null;
  day_high?: number | null;
  day_low?: number | null;
  source?: string | null;
  freshness_label?: string | null;
  license_tag?: string | null;
};

function pctClass(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "text-qa-muted";
  if (value > 0.02) return "text-terminal-up";
  if (value < -0.02) return "text-terminal-down";
  return "text-qa-muted";
}

function fmtPct(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

function fmtPrice(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  if (Math.abs(value) >= 1000) return value.toLocaleString("en-US", { maximumFractionDigits: 2 });
  return value.toFixed(2);
}

function fmtVol(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value) || value <= 0) return "—";
  if (value >= 1_000_000_000) return `${(value / 1_000_000_000).toFixed(1)}B`;
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(0)}K`;
  return String(Math.round(value));
}

function QuoteTable({ title, rows }: { title: string; rows: QuoteRow[] }) {
  const live = rows.filter((r) => typeof r.price === "number" || typeof r.change_pct === "number").length;
  return (
    <section className="cockpit-panel overflow-hidden min-w-0">
      <h2 className="px-3 py-2 text-[10px] uppercase tracking-wide text-qa-muted border-b border-cockpit-border flex items-center justify-between gap-2">
        <span>{title}</span>
        {rows.length > 0 ? (
          <span className="normal-case tracking-normal font-normal tabular-nums">
            {live}/{rows.length}
          </span>
        ) : null}
      </h2>
      <div className="overflow-x-auto">
        <table className="w-full text-[11px] min-w-[320px]">
          <thead>
            <tr className="text-[9px] uppercase tracking-wide text-qa-muted border-b border-cockpit-border/80">
              <th className="px-3 py-1 text-left font-normal">Тикер</th>
              <th className="px-2 py-1 text-right font-normal">Цена</th>
              <th className="px-2 py-1 text-right font-normal hidden lg:table-cell">Свежесть</th>
              <th className="px-2 py-1 text-right font-normal">Δ%</th>
              <th className="px-2 py-1 text-right font-normal hidden sm:table-cell">Объём</th>
              <th className="px-2 py-1 text-right font-normal hidden md:table-cell">Max</th>
              <th className="px-3 py-1 text-right font-normal hidden md:table-cell">Min</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.symbol} className="border-b border-cockpit-border/60 last:border-0 hover:bg-white/[0.02]">
                <td className="px-3 py-1.5">
                  <Link
                    href={`/cockpit/${encodeURIComponent(row.symbol)}`}
                    className="font-mono font-semibold text-white hover:text-terminal-accent"
                  >
                    {row.symbol}
                  </Link>
                  <div className="text-[10px] text-qa-muted">{row.name}</div>
                </td>
                <td className="px-2 py-1.5 tabular-nums text-right text-qa-text">{fmtPrice(row.price)}</td>
                <td
                  data-testid="quote-freshness"
                  className="px-2 py-1.5 text-right text-[10px] text-qa-muted hidden lg:table-cell"
                >
                  {row.freshness_label?.trim() || "нет данных"}
                </td>
                <td className={clsx("px-2 py-1.5 tabular-nums text-right font-medium", pctClass(row.change_pct))}>
                  {fmtPct(row.change_pct)}
                </td>
                <td className="px-2 py-1.5 tabular-nums text-right text-qa-muted hidden sm:table-cell">
                  {fmtVol(row.volume)}
                </td>
                <td className="px-2 py-1.5 tabular-nums text-right text-qa-muted hidden md:table-cell">
                  {fmtPrice(row.day_high)}
                </td>
                <td className="px-3 py-1.5 tabular-nums text-right text-qa-muted hidden md:table-cell">
                  {fmtPrice(row.day_low)}
                </td>
              </tr>
            ))}
            {!rows.length ? (
              <tr>
                <td colSpan={7} className="px-3 py-4 text-xs text-qa-muted">
                  Нет строк для этой группы
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function CompareChart({
  series,
}: {
  series: Record<string, Array<{ date: string; pct: number }>>;
}) {
  const colors: Record<string, string> = { SPY: "#60a5fa", QQQ: "#34d399", IWM: "#f472b6" };
  const points = useMemo(() => {
    const keys = Object.keys(series);
    const n = Math.max(0, ...keys.map((k) => series[k]?.length ?? 0));
    if (!n) return null;
    const w = 520;
    const h = 180;
    const pad = 8;
    const paths: Record<string, string> = {};
    for (const key of keys) {
      const rows = series[key] ?? [];
      if (rows.length < 2) continue;
      const ys = rows.map((r) => r.pct);
      const min = Math.min(...ys, 0);
      const max = Math.max(...ys, 0);
      const span = max - min || 1;
      const d = rows
        .map((r, i) => {
          const x = pad + (i / (rows.length - 1)) * (w - pad * 2);
          const y = h - pad - ((r.pct - min) / span) * (h - pad * 2);
          return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
        })
        .join(" ");
      paths[key] = d;
    }
    return { w, h, paths };
  }, [series]);

  if (!points || Object.keys(points.paths).length === 0) {
    return (
      <p className="text-xs text-qa-muted px-3 py-6">
        Кривые сравнения пока недоступны — нет дневных баров по SPY/QQQ/IWM.
      </p>
    );
  }

  return (
    <svg viewBox={`0 0 ${points.w} ${points.h}`} className="w-full h-48">
      {Object.entries(points.paths).map(([key, d]) => (
        <path key={key} d={d} fill="none" stroke={colors[key] || "#94a3b8"} strokeWidth="1.8" />
      ))}
    </svg>
  );
}

export function MarketsOverview() {
  const { data, isLoading, isError, isFetching, refetch } = useQuery({
    queryKey: ["market-overview"],
    queryFn: () => marketApi.overview(),
    staleTime: 60_000,
    refetchInterval: 90_000,
    retry: 2,
  });
  const analysisQuery = useQuery({
    queryKey: ["market-analysis"],
    queryFn: () => marketApi.analysis(),
    staleTime: 60_000,
    retry: 1,
  });

  const groups = (data?.groups as Record<string, QuoteRow[]> | undefined) ?? {};
  const news = (Array.isArray(data?.news) ? data.news : []) as Array<Record<string, unknown>>;
  const macro = (Array.isArray(data?.macro) ? data.macro : []) as Array<Record<string, unknown>>;
  const matrix = (Array.isArray(data?.fx_matrix) ? data.fx_matrix : []) as Array<{
    row: string;
    col: string;
    delta: number | null;
  }>;
  const compare = (data?.compare as Record<string, Array<{ date: string; pct: number }>>) ?? {};
  const fxSymbols = (groups.fx ?? []).map((r) => r.symbol);
  const coverage =
    typeof data?.coverage === "number"
      ? data.coverage
      : Object.values(groups).reduce(
          (acc, rows) =>
            acc + rows.filter((r) => typeof r.price === "number" || typeof r.change_pct === "number").length,
          0,
        );
  const regime = typeof data?.regime === "string" && data.regime.trim() ? data.regime.trim() : null;
  const thin = !isLoading && coverage < 5;
  const dataLayer = (data?.data_layer as Record<string, Record<string, unknown>> | undefined) ?? {};
  const eodSync = dataLayer.equity_eod?.synced_at ? String(dataLayer.equity_eod.synced_at) : null;
  const stooqSync = dataLayer.stooq?.synced_at ? String(dataLayer.stooq.synced_at) : null;
  const quoteSync = stooqSync || eodSync;

  const analysis = analysisQuery.data;
  const analysisRegime =
    analysis && typeof analysis === "object"
      ? (analysis.regime as { label?: string } | undefined)
      : undefined;
  const analysisText =
    analysis && typeof analysis === "object"
      ? (analysis.text as { phrase?: string } | undefined)
      : undefined;
  const calendar =
    analysis && typeof analysis === "object"
      ? (analysis.calendar as { data_status?: string } | undefined)
      : undefined;

  if (isLoading) {
    return (
      <div className="cockpit-panel p-8 text-sm text-qa-muted">
        Собираем индексы, сектора, валюты и новости…
      </div>
    );
  }
  if (isError) {
    return (
      <div className="cockpit-panel p-8 space-y-3">
        <p className="text-sm text-terminal-down">Сводку рынка сейчас не удалось собрать.</p>
        <button type="button" className="btn-secondary text-xs" onClick={() => void refetch()}>
          Повторить
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <section className="cockpit-panel px-4 py-3" data-testid="market-analysis">
        <p className="text-[10px] uppercase tracking-wide text-qa-muted mb-1">Анализ рынка</p>
        <p data-testid="market-regime-label" className="text-sm text-white">
          {analysisRegime?.label || analysisText?.phrase || "нет данных"}
        </p>
        {analysisText?.phrase ? (
          <p className="text-xs text-qa-muted mt-1">{analysisText.phrase}</p>
        ) : null}
        <p data-testid="market-calendar-status" className="text-[10px] text-qa-muted mt-2">
          Календарь: {calendar?.data_status || "нет данных"}
        </p>
      </section>
      {regime ? (
        <div className="cockpit-panel px-4 py-3">
          <p className="text-[10px] uppercase tracking-wide text-qa-muted mb-1">Режим дня</p>
          <p className="text-sm text-white leading-relaxed">{regime}</p>
          <p className="text-[10px] text-qa-muted mt-1.5 tabular-nums">
            покрытие {coverage}
            {quoteSync ? ` · котировки ${quoteSync.slice(0, 16).replace("T", " ")}` : " · котировки не загружены"}
          </p>
          {data?.stale ? (
            <p className="text-[10px] text-amber-400/90 mt-1">Показана последняя удачная сводка — данные могли устареть.</p>
          ) : null}
        </div>
      ) : thin ? (
        <div className="cockpit-panel px-4 py-3 flex flex-wrap items-center justify-between gap-2">
          <div className="min-w-0">
            <p className="text-sm text-qa-muted leading-relaxed">
              сводка рынка ещё собирается — обновите страницу через минуту
            </p>
            <p className="text-[10px] text-qa-muted mt-1">
              {quoteSync
                ? `котировки ${quoteSync.slice(0, 19).replace("T", " ")}`
                : "котировки ещё не загружены"}
            </p>
          </div>
          <button
            type="button"
            disabled={isFetching}
            className="btn-secondary text-xs shrink-0"
            onClick={() => void refetch()}
          >
            {isFetching ? "Обновляем…" : "Обновить"}
          </button>
        </div>
      ) : null}

      {macro.length > 0 ? (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
          {macro.map((row) => (
            <div key={String(row.id)} className="cockpit-panel px-3 py-2">
              <div className="text-[10px] uppercase text-qa-muted">{String(row.label)}</div>
              <div className="text-lg tabular-nums font-semibold">
                {typeof row.value === "number" ? row.value.toFixed(2) : "—"}
              </div>
              <div className="text-[10px] text-qa-muted">{String(row.date || "")}</div>
            </div>
          ))}
        </div>
      ) : null}

      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)_minmax(0,1fr)] gap-3 items-start">
        <div className="space-y-3">
          <QuoteTable title="Акции США" rows={groups.us_equity ?? []} />
          <QuoteTable title="Секторы США" rows={groups.us_sectors ?? []} />
          <QuoteTable title="Облигации" rows={groups.fixed_income ?? []} />
        </div>
        <div className="space-y-3">
          <section className="cockpit-panel">
            <h2 className="px-3 py-2 text-[10px] uppercase tracking-wide text-qa-muted border-b border-cockpit-border">
              Сравнение с начала периода
            </h2>
            <div className="flex gap-3 px-3 pt-2 text-[10px]">
              <span className="text-sky-400">S&P 500</span>
              <span className="text-emerald-400">Nasdaq 100</span>
              <span className="text-pink-400">малые компании</span>
            </div>
            <CompareChart series={compare} />
          </section>
          <section className="cockpit-panel">
            <h2 className="px-3 py-2 text-[10px] uppercase tracking-wide text-qa-muted border-b border-cockpit-border">
              Новости рынка
            </h2>
            <ul className="divide-y divide-cockpit-border">
              {news.slice(0, 8).map((item, idx) => {
                const tickers = Array.isArray(item.tickers) ? item.tickers : Array.isArray(item.tickers_mentioned) ? item.tickers_mentioned : [];
                const ticker = typeof tickers[0] === "string" ? tickers[0] : "";
                return (
                <li key={idx} className="px-3 py-2" data-testid="market-news-item">
                  <a
                    href={String(item.url || "#")}
                    target="_blank"
                    rel="noreferrer"
                    className="text-xs text-qa-text hover:text-terminal-accent leading-relaxed"
                  >
                    {String(item.title || "без заголовка")}
                  </a>
                  {ticker ? <CrossActions ticker={ticker} variant="menu" /> : null}
                </li>
              );})}
              {!news.length ? (
                <li className="px-3 py-4 text-xs text-qa-muted">
                  Лента новостей сейчас пуста — источник временно не отдал заголовки.
                </li>
              ) : null}
            </ul>
          </section>
        </div>
        <div className="space-y-3">
          <QuoteTable title="Валюты" rows={groups.fx ?? []} />
          <QuoteTable title="Мир" rows={groups.global ?? []} />
          <QuoteTable title="Сырьё и крипто" rows={groups.commodities ?? []} />
        </div>
      </div>

      {fxSymbols.length > 1 ? (
        <section className="cockpit-panel overflow-x-auto">
          <h2 className="px-3 py-2 text-[10px] uppercase tracking-wide text-qa-muted border-b border-cockpit-border">
            Кто сегодня сильнее среди валютных фондов
          </h2>
          <table className="text-[10px] font-mono min-w-[420px]">
            <thead>
              <tr>
                <th className="p-1" />
                {fxSymbols.map((s) => (
                  <th key={s} className="p-1 text-qa-muted font-normal">
                    {s}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {fxSymbols.map((row) => (
                <tr key={row}>
                  <td className="p-1 text-qa-muted">{row}</td>
                  {fxSymbols.map((col) => {
                    const cell = matrix.find((m) => m.row === row && m.col === col);
                    const v = cell?.delta;
                    return (
                      <td key={col} className="p-0.5">
                        <div
                          className={clsx(
                            "w-12 h-7 flex items-center justify-center rounded tabular-nums",
                            v == null
                              ? "text-qa-muted"
                              : v > 0.15
                                ? "bg-terminal-up/30 text-terminal-up"
                                : v < -0.15
                                  ? "bg-terminal-down/30 text-terminal-down"
                                  : "text-qa-muted",
                          )}
                        >
                          {v == null ? "—" : v.toFixed(1)}
                        </div>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : null}
    </div>
  );
}
