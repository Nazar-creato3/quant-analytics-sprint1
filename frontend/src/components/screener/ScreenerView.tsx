"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { clsx } from "clsx";
import { forecastApi, marketApi, type ForecastMlSignal } from "@/lib/api";
import { useActiveTicker } from "@/contexts/ActiveTickerContext";
import { useAuth } from "@/hooks";
import { formatMlSignal } from "@/lib/ml-forecast-signal";
import { prefetchTickerDesk } from "@/lib/prefetch-ticker-desk";
import {
  DEFAULT_SCREENER_DRAFT,
  SCREENER_COUNTRIES,
  SCREENER_PRESETS,
  SCREENER_SECTORS,
  SCREENER_SIZES,
  draftToScreenerParams,
  sectorLabel,
  sizeIdOf,
  sortScreenerRows,
  terminalHrefForTicker,
  type ScreenerDraft,
  type ScreenerSortKey,
} from "@/lib/screener";
import { CrossActions } from "@/components/shared/CrossActions";
import { Spinner } from "@/components/ui";

const DASH = "—";

function fmtNum(value: number | null | undefined, status?: string | null, digits = 2): string {
  if (status === "нет данных" || value == null || !Number.isFinite(value)) return DASH;
  return value.toLocaleString("ru-RU", { maximumFractionDigits: digits, minimumFractionDigits: digits });
}

function fmtCap(value: number | null | undefined, rub = false): string {
  if (value == null || !Number.isFinite(value)) return DASH;
  const [pre, post] = rub ? ["", " ₽"] : ["$", ""];
  if (Math.abs(value) >= 1e12) return `${pre}${(value / 1e12).toLocaleString("ru-RU", { maximumFractionDigits: 2 })} трлн${post}`;
  if (Math.abs(value) >= 1e9) return `${pre}${(value / 1e9).toLocaleString("ru-RU", { maximumFractionDigits: 1 })} млрд${post}`;
  if (Math.abs(value) >= 1e6) return `${pre}${(value / 1e6).toLocaleString("ru-RU", { maximumFractionDigits: 0 })} млн${post}`;
  return value.toFixed(0);
}

function fmtVol(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return DASH;
  if (value >= 1e9) return `${(value / 1e9).toLocaleString("ru-RU", { maximumFractionDigits: 1 })} млрд`;
  if (value >= 1e6) return `${(value / 1e6).toLocaleString("ru-RU", { maximumFractionDigits: 1 })} млн`;
  if (value >= 1e3) return `${(value / 1e3).toFixed(0)} тыс.`;
  return value.toFixed(0);
}

const SELECT =
  "w-full bg-cockpit-panel border border-cockpit-border rounded-md px-2.5 py-2 text-sm text-qa-text focus:border-terminal-accent focus:outline-none";

function Select({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: Array<{ value: string; label: string }>;
}) {
  return (
    <label className="text-xs text-qa-muted space-y-1 min-w-0">
      <span>{label}</span>
      <select className={SELECT} value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function Field({
  label,
  value,
  onChange,
  placeholder,
  mono,
  hint,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  mono?: boolean;
  hint?: string;
}) {
  return (
    <label className="text-xs text-qa-muted space-y-1 min-w-0" title={hint}>
      <span>{label}</span>
      <input
        inputMode="decimal"
        className={clsx(
          "w-full bg-cockpit-panel border border-cockpit-border rounded-md px-2.5 py-2 text-sm text-qa-text focus:border-terminal-accent focus:outline-none",
          mono && "tabular-nums",
        )}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  );
}

export function ScreenerView() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { isStaff } = useAuth();
  const { setActiveTicker } = useActiveTicker();
  const [draft, setDraft] = useState<ScreenerDraft>(DEFAULT_SCREENER_DRAFT);
  const [applied, setApplied] = useState(() => draftToScreenerParams(DEFAULT_SCREENER_DRAFT));
  const [sortKey, setSortKey] = useState<ScreenerSortKey>("market_cap");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [opening, setOpening] = useState<string | null>(null);

  const [more, setMore] = useState(false);
  // Filters apply by themselves a moment after the last change — no «Показать» button.
  useEffect(() => {
    const id = setTimeout(() => setApplied(draftToScreenerParams(draft)), 450);
    return () => clearTimeout(id);
  }, [draft]);
  const patch = (partial: Partial<ScreenerDraft>) => setDraft((d) => ({ ...d, ...partial }));

  const { data, isFetching, isError, dataUpdatedAt } = useQuery({
    queryKey: ["fmp-screener", applied],
    queryFn: () => marketApi.screener(applied),
    staleTime: 60_000,
  });

  const rows = useMemo(
    () => sortScreenerRows(data ?? [], sortKey, sortDir),
    [data, sortKey, sortDir],
  );
  const symbols = useMemo(() => rows.map((r) => r.symbol), [rows]);
  const signalsQ = useQuery({
    queryKey: ["forecast-signals", "screener", symbols.join(",")],
    queryFn: () => forecastApi.signals(symbols),
    staleTime: 60_000,
    enabled: symbols.length > 0,
  });
  const mlBySym = useMemo(() => {
    const map = new Map<string, ForecastMlSignal>();
    for (const item of signalsQ.data ?? []) map.set(item.symbol.toUpperCase(), item);
    return map;
  }, [signalsQ.data]);

  const applyPreset = (partial: Partial<ScreenerDraft>) => {
    const next = { ...DEFAULT_SCREENER_DRAFT, ...partial };
    setDraft(next);
    setApplied(draftToScreenerParams(next));
  };

  const toggleSort = (key: ScreenerSortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
      return;
    }
    setSortKey(key);
    setSortDir(key === "symbol" || key === "name" ? "asc" : "desc");
  };

  const openInTerminal = (symbol: string) => {
    setOpening(symbol);
    setActiveTicker(symbol, { syncUrl: false });
    void prefetchTickerDesk(queryClient, symbol);
    router.push(terminalHrefForTicker(symbol, Boolean(isStaff)));
  };

  const header = (key: ScreenerSortKey, label: string, right?: boolean, hint?: string) => (
    <th className={clsx("px-3 py-2 font-medium", right && "text-right")} title={hint}>
      <button type="button" className="hover:text-qa-text" onClick={() => toggleSort(key)}>
        {label}
        {sortKey === key ? (sortDir === "asc" ? " ↑" : " ↓") : ""}
      </button>
    </th>
  );

  return (
    <div className="space-y-4 flex flex-col min-h-0">
      <div className="card p-4 space-y-4">
        <div className="flex flex-wrap gap-2" role="group" aria-label="Готовые подборки">
          {SCREENER_PRESETS.map((p) => {
            const active = JSON.stringify(draftToScreenerParams({ ...DEFAULT_SCREENER_DRAFT, ...p.draft })) === JSON.stringify(applied);
            return (
              <button
                key={p.id}
                type="button"
                aria-pressed={active}
                className={clsx(
                  "px-3 py-1.5 text-xs rounded-full border transition-colors",
                  active
                    ? "bg-terminal-accent text-black border-terminal-accent font-semibold"
                    : "text-qa-text/85 border-cockpit-border hover:border-terminal-accent hover:text-terminal-accent",
                )}
                onClick={() => applyPreset(p.draft)}
              >
                {p.label}
              </button>
            );
          })}
        </div>

        <div className="grid gap-3 grid-cols-2 lg:grid-cols-6 items-end">
          <Select label="Рынок" value={draft.country} onChange={(v) => patch({ country: v })} options={SCREENER_COUNTRIES} />
          <Select label="Отрасль" value={draft.sector} onChange={(v) => patch({ sector: v })} options={SCREENER_SECTORS} />
          <Select
            label="Размер компании"
            value={sizeIdOf(draft)}
            onChange={(id) => {
              const size = SCREENER_SIZES.find((x) => x.id === id);
              if (size) patch({ mcapMin: size.min, mcapMax: size.max });
            }}
            options={[
              ...SCREENER_SIZES.map((x) => ({ value: x.id, label: x.label })),
              ...(sizeIdOf(draft) === "custom" ? [{ value: "custom", label: "Свой диапазон" }] : []),
            ]}
          />
          <Field label="Цена акции до" value={draft.priceMax} onChange={(v) => patch({ priceMax: v })} placeholder="любая" mono />
          <Field label="Дивиденды от, %" value={draft.dividendMin} onChange={(v) => patch({ dividendMin: v })} placeholder="любые" mono />
          <label className="flex items-center gap-2 text-xs text-qa-text pb-2.5">
            <input type="checkbox" checked={draft.isEtf} onChange={(e) => patch({ isEtf: e.target.checked })} />
            Только фонды (ETF)
          </label>
        </div>

        <div>
          <button
            type="button"
            className="text-xs text-qa-muted hover:text-terminal-accent"
            aria-expanded={more}
            onClick={() => setMore((v) => !v)}
          >
            {more ? "▾ Скрыть дополнительные фильтры" : "▸ Дополнительные фильтры: риск, оценка, оборот"}
          </button>
          {more ? (
            <div className="mt-3 grid gap-3 grid-cols-2 lg:grid-cols-6">
              <Field label="P/E не выше" value={draft.peMax} onChange={(v) => patch({ peMax: v })} mono hint="Цена акции к прибыли на акцию: сколько лет прибыли вы платите" />
              <Field label="Бета от" value={draft.betaMin} onChange={(v) => patch({ betaMin: v })} mono hint="Насколько бумага сильнее рынка: 1 — как рынок, 2 — вдвое сильнее" />
              <Field label="Волатильность от" value={draft.volMin} onChange={(v) => patch({ volMin: v })} mono hint="Годовой размах колебаний цены, доля: 0,3 = 30%" />
              <Field label="Убыток в худшие дни от" value={draft.esMin} onChange={(v) => patch({ esMin: v })} mono hint="Средний дневной убыток в 2,5% худших дней (ES 97,5)" />
              <Field label="Оборот за день от, шт." value={draft.volumeMin} onChange={(v) => patch({ volumeMin: v })} mono />
              <Field label="Цена акции от" value={draft.priceMin} onChange={(v) => patch({ priceMin: v })} mono />
              <Field label="Биржа" value={draft.exchange} onChange={(v) => patch({ exchange: v.toUpperCase() })} placeholder="NASDAQ, NYSE, MOEX" />
              <Field label="Отрасль подробнее" value={draft.industry} onChange={(v) => patch({ industry: v })} placeholder="например, Semiconductors" />
              <Field label="Сколько показать" value={draft.limit} onChange={(v) => patch({ limit: v })} mono />
            </div>
          ) : null}
        </div>

        <div className="flex flex-wrap items-center gap-2 border-t border-cockpit-border pt-3">
          <button type="button" className="btn-ghost text-xs" onClick={() => applyPreset({})}>
            Сбросить фильтры
          </button>
          <button type="button" className="btn-ghost text-xs" onClick={() => void marketApi.saveScreener("текущий", applied)}>
            Сохранить подборку
          </button>
          <a
            className="btn-ghost text-xs"
            href="/api/v1/market/screener/export"
            onClick={(e) => {
              e.preventDefault();
              const q = new URLSearchParams();
              if (applied.country) q.set("country", String(applied.country));
              if (applied.sector) q.set("sector", String(applied.sector));
              window.open(`/api/v1/market/screener/export?${q.toString()}`, "_blank");
            }}
          >
            Скачать таблицу (CSV)
          </a>
        </div>
      </div>

      <div className="cockpit-panel overflow-auto flex-1 min-h-[320px]">
        <div className="px-3 py-2 text-[11px] text-qa-muted border-b border-cockpit-border flex justify-between">
          <span>
            Найдено: {rows.length}
            {dataUpdatedAt ? ` · ${new Date(dataUpdatedAt).toLocaleTimeString("ru-RU")}` : ""}
          </span>
          {isFetching && (
            <span className="inline-flex items-center gap-1">
              <Spinner size={12} /> ищем…
            </span>
          )}
        </div>
        {isError && (
          <p className="p-4 text-sm text-qa-muted">Не удалось загрузить список бумаг. Попробуйте ещё раз через минуту.</p>
        )}
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-cockpit-panel z-[1]">
            <tr className="text-left text-[11px] text-qa-muted border-b border-cockpit-border">
              {header("symbol", "Тикер")}
              {header("name", "Компания")}
              <th className="px-3 py-2 font-medium">Биржа</th>
              <th className="px-3 py-2 font-medium">Отрасль</th>
              {header("price", "Цена", true)}
              {header("market_cap", "Капитализация", true, "Стоимость всех акций компании")}
              {header("pe", "P/E", true, "Цена к прибыли: сколько лет прибыли вы платите")}
              <th className="px-3 py-2 text-right font-medium" title="Дивиденды за 12 месяцев к текущей цене">Див. доходность</th>
              {header("beta", "Бета", true, "Сила движения относительно рынка: 1 — как рынок")}
              {header("volatility", "Колебания", true, "Годовая волатильность цены")}
              {header("es_975", "Худшие дни", true, "Средний убыток в 2,5% худших дней (ES 97,5)")}
              {header("volume", "Оборот", true, "Сколько бумаг проходит за день")}
              <th className="px-3 py-2 text-right font-medium" title="Направление по прогнозной модели на ближайший горизонт">Прогноз</th>
              <th className="px-3 py-2 font-medium" aria-label="Действия" />
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const ml = formatMlSignal(mlBySym.get(row.symbol.toUpperCase()));
              return (
                <tr
                  key={row.symbol}
                  className={clsx(
                    "border-b border-cockpit-border/50 hover:bg-cockpit-panel-raised cursor-pointer",
                    opening === row.symbol && "bg-terminal-accent-muted",
                  )}
                  onClick={() => openInTerminal(row.symbol)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") openInTerminal(row.symbol);
                  }}
                  tabIndex={0}
                >
                  <td className="px-3 py-2 font-mono font-semibold">{row.symbol}</td>
                  <td className="px-3 py-2 truncate max-w-[260px]">{row.name && row.name !== row.symbol ? row.name : DASH}</td>
                  <td className="px-3 py-2 text-qa-muted">{row.exchange ?? "—"}</td>
                  <td className="px-3 py-2 text-qa-muted truncate max-w-[160px]">{sectorLabel(row.sector)}</td>
                  <td className="px-3 py-2 text-right font-mono">
                    {row.price == null ? DASH : `${fmtNum(row.price)} ${row.currency === "RUB" ? "₽" : "$"}`}
                  </td>
                  <td className="px-3 py-2 text-right font-mono">
                    {row.currency === "RUB" ? fmtCap(row.market_cap_rub, true) : fmtCap(row.market_cap)}
                  </td>
                  <td data-testid="screener-pe" className="px-3 py-2 text-right font-mono">
                    {fmtNum(row.pe, row.pe_status, 1)}
                  </td>
                  <td className="px-3 py-2 text-right font-mono">{row.dividend == null ? DASH : `${fmtNum(row.dividend * 100, null, 1)}%`}</td>
                  <td className="px-3 py-2 text-right font-mono">{fmtNum(row.beta, row.beta_status)}</td>
                  <td className="px-3 py-2 text-right font-mono">{row.volatility == null ? DASH : `${fmtNum(row.volatility * 100, null, 0)}%`}</td>
                  <td className="px-3 py-2 text-right font-mono">{row.es_975 == null || row.es_status === "нет данных" ? DASH : `${fmtNum(Math.abs(row.es_975) * 100, null, 1)}%`}</td>
                  <td className="px-3 py-2 text-right font-mono">{fmtVol(row.volume)}</td>
                  <td className={clsx("px-3 py-2 text-right font-mono text-[11px]", ml.cls)}>{ml.text}</td>
                  <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
                    <CrossActions ticker={row.symbol} variant="menu" />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {!isFetching && rows.length === 0 && (
          <p className="p-4 text-sm text-qa-muted">Под эти условия ничего не подошло. Ослабьте фильтры или выберите готовую подборку выше.</p>
        )}
      </div>
    </div>
  );
}
