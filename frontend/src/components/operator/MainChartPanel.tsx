"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { marketApi, maneuversApi, robotApi } from "@/lib/api";
import { BARS_POLL_MS, QUOTE_POLL_MS } from "@/lib/marketPoll";
import { LightweightChart } from "@/components/charts/LightweightChart";
import { PriceChart } from "@/components/charts/PriceChart";
import { ChartTypeToggle, type ChartDisplayType } from "@/components/charts/ChartTypeToggle";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";
import { CockpitPanelHeader } from "./CockpitPanelHeader";
import { ReasonState } from "./ReasonState";
import type { Maneuver } from "@/types";
import {
  formatExpectedPnlRange,
  formatTpHitProbability,
  formatUsdPnl,
} from "@/lib/profit-projection";
import { NameDeskCard, NameDeskToggle } from "./NameDeskCard";
import { RobotPanel } from "./RobotPanel";
import { oscillatorCopy, rsi14, macdHistogram } from "@/components/charts/oscillators";
import { useLocale } from "@/contexts/LocaleContext";
import { useFreshnessClock } from "@/hooks/useLiveFreshness";

interface MainChartPanelProps {
  ticker: string;
  position?: Maneuver | null;
  compact?: boolean;
  className?: string;
  chartEngine?: "recharts" | "lightweight";
  /** Fixed chart height — disables flex resize observer (prevents stretch bugs). */
  fixedHeight?: number;
  /** Widescreen desk: show statement under the chart (not as overlay). */
  statementUnderChart?: boolean;
}

const LIVE_BARS_REFRESH_MS = BARS_POLL_MS;
const LIVE_QUOTE_REFRESH_MS = QUOTE_POLL_MS;

function formatUsd(value: number): string {
  return formatUsdPnl(value);
}

export function MainChartPanel({
  ticker,
  position,
  compact = false,
  className,
  chartEngine = "lightweight",
  fixedHeight,
  statementUnderChart = false,
}: MainChartPanelProps) {
  const { t, locale } = useLocale();
  const qc = useQueryClient();
  const router = useRouter();
  const chartHref = ticker
    ? `/operator/chart?symbol=${encodeURIComponent(ticker)}&desk=1`
    : "/operator/chart";
  const chartAreaRef = useRef<HTMLDivElement>(null);
  const [chartType, setChartType] = useState<ChartDisplayType>("candlestick");
  const [timeframe, setTimeframe] = useState<"5m" | "15m" | "1h" | "4h" | "1d" | "1w">("1d");
  const [deskOpen, setDeskOpen] = useState(statementUnderChart);
  const [shadowEquity, setShadowEquity] = useState<number[]>([]);
  const defaultHeight = fixedHeight ?? (compact ? 160 : 440);
  const [chartHeight, setChartHeight] = useState(defaultHeight);

  const quoteForceRef = useRef(true);
  const barsForceRef = useRef(true);

  useEffect(() => {
    quoteForceRef.current = true;
    barsForceRef.current = true;
  }, [ticker]);

  useEffect(() => {
    setChartHeight(fixedHeight ?? (compact ? 160 : 440));
  }, [fixedHeight, compact, ticker]);

  useEffect(() => {
    setShadowEquity([]);
  }, [ticker]);

  useEffect(() => {
    if (statementUnderChart) setDeskOpen(true);
  }, [statementUnderChart, ticker]);

  const barLimit = timeframe === "1d" ? (compact ? 60 : 120) : compact ? 80 : 180;
  const { data: bars, isLoading, error, dataUpdatedAt } = useQuery({
    queryKey: ["bars", ticker, timeframe, compact ? "operator-compact" : "operator-full"],
    queryFn: () => {
      const force = barsForceRef.current;
      barsForceRef.current = false;
      return marketApi.getBars(ticker, timeframe, barLimit, { forceRefresh: force });
    },
    staleTime: LIVE_BARS_REFRESH_MS,
    refetchInterval: compact ? false : LIVE_BARS_REFRESH_MS,
    refetchIntervalInBackground: true,
    enabled: !!ticker,
    retry: 1,
    refetchOnMount: "always",
  });

  const { data: quote, dataUpdatedAt: quoteUpdatedAt } = useQuery({
    queryKey: ["quote", ticker],
    queryFn: () => {
      const force = quoteForceRef.current;
      quoteForceRef.current = false;
      return marketApi.getQuote(ticker, { forceRefresh: force, enrich: true });
    },
    staleTime: LIVE_QUOTE_REFRESH_MS,
    refetchInterval: LIVE_QUOTE_REFRESH_MS,
    refetchIntervalInBackground: true,
    enabled: !!ticker,
    retry: 1,
  });

  const { data: book } = useQuery({
    queryKey: ["ticker-book", ticker],
    queryFn: () => maneuversApi.book(ticker),
    staleTime: 15_000,
    refetchInterval: compact ? false : 30_000,
    enabled: !!ticker && !compact,
    retry: 1,
  });

  const { data: robotBook } = useQuery({
    queryKey: ["robot-book", ticker],
    queryFn: () => robotApi.book(ticker),
    staleTime: 15_000,
    refetchInterval: compact ? false : 30_000,
    enabled: !!ticker && !compact,
    retry: 1,
    // Robot Core is additive — chart must stay usable if endpoint fails
    throwOnError: false,
  });

  const livePrice = typeof quote?.price === "number" ? quote.price : null;
  const companyName = [
    quote?.short_name,
    quote?.name,
    quote?.long_name,
    quote?.company_name,
  ].find((v) => typeof v === "string" && v.trim()) as string | undefined;

  useEffect(() => {
    if (fixedHeight != null) return;
    const el = chartAreaRef.current;
    if (!el) return;

    const measure = () => {
      const h = el.clientHeight;
      const padding = compact ? 16 : 24;
      if (h > 0) setChartHeight(Math.max(180, Math.min(h - padding, 720)));
    };

    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [compact, fixedHeight, ticker]);

  const showOverlay = !!position && position.ticker === ticker;
  const entryPrice = showOverlay ? position!.fill_price ?? position!.entry_zone_high ?? null : null;
  const avgEntryPrice =
    robotBook?.avg_entry ?? book?.avg_entry ?? position?.avg_entry_price ?? entryPrice;
  const dualBook = !!(robotBook?.dual || book?.dual);
  const avgLongPrice = dualBook
    ? (robotBook?.avg_long ?? book?.avg_long ?? null)
    : null;
  const avgShortPrice = dualBook
    ? (robotBook?.avg_short ?? book?.avg_short ?? null)
    : null;
  const breakevenPrice = robotBook?.breakeven ?? book?.breakeven ?? null;
  const beLong = robotBook?.breakeven_long ?? null;
  const beShort = robotBook?.breakeven_short ?? null;
  const beNet = robotBook?.net_breakeven ?? breakevenPrice;
  const strategyLow = book?.strategy_low ?? null;
  const strategyHigh = book?.strategy_high ?? null;
  const stopLoss = showOverlay ? position!.stop_loss : null;
  const takeProfit = showOverlay ? position!.take_profit : null;
  const currentPrice = showOverlay
    ? position!.current_price ?? livePrice ?? bars?.[bars.length - 1]?.close ?? null
    : livePrice ?? book?.mark_price ?? bars?.[bars.length - 1]?.close ?? null;
  const unrealizedPnl = showOverlay
    ? position!.unrealized_pnl ?? book?.unrealized_usd ?? null
    : book?.unrealized_usd ?? null;
  const projectedProfit = showOverlay ? position!.approx_profit ?? null : null;
  const tradeMarkers = book?.markers ?? [];
  const activePlan = robotBook?.plans?.[0] ?? null;
  const robotActive = !!activePlan && activePlan.status === "active";
  const robotLevels =
    activePlan?.levels
      ?.filter((lv) => typeof lv.price === "number" && Number.isFinite(lv.price) && lv.price > 0)
      .map((lv) => ({
        kind: lv.kind,
        price: lv.price as number,
        status: lv.status,
        title:
          lv.kind === "add"
            ? `Add ${lv.size_pct != null ? `${lv.size_pct}%` : ""}`.trim()
            : undefined,
      })) ?? [];
  const avgZoneHint =
    book?.avg_entry != null && book.avg_in_strategy_zone != null
      ? book.avg_in_strategy_zone
        ? "Avg в зоне входа"
        : "Avg вне зоны входа"
      : null;
  const netSideLabel =
    robotBook?.side === "dual" || book?.net_side === "dual"
      ? "Dual"
      : robotBook?.side === "short" || book?.net_side === "short"
        ? "Sell"
        : "Buy";
  const lotsHint =
    robotBook && robotBook.open_lots > 0
      ? ` · лотов ${robotBook.open_lots}`
      : book?.open_legs
        ? ` · ног ${book.open_legs}`
        : null;
  const fundingHint =
    robotBook?.funding_usd != null && robotBook.funding_usd > 0
      ? ` · funding $${robotBook.funding_usd.toFixed(2)}`
      : null;

  const tickNow = useFreshnessClock();
  const lastLiveAt = Math.max(dataUpdatedAt || 0, quoteUpdatedAt || 0);
  const updatedLabel = showOverlay
    ? new Date(tickNow).toLocaleTimeString(locale, {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      })
    : lastLiveAt
      ? new Date(lastLiveAt).toLocaleTimeString(locale, {
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
        })
      : null;

  const osc = bars?.length ? oscillatorCopy(rsi14(bars), macdHistogram(bars)) : null;

  const headerExtra = (
    <div className="flex items-center gap-2">
      {(["5m", "15m", "1h", "4h", "1d", "1w"] as const).map((tf) => (
        <button
          key={tf}
          type="button"
          onClick={() => setTimeframe(tf)}
          className={clsx(
            "text-[10px] px-1.5 py-0.5 rounded border",
            timeframe === tf ? "border-terminal-accent/50 text-terminal-accent" : "border-qa-border text-qa-muted",
          )}
        >
          {t(`chart.tf.${tf}`)}
        </button>
      ))}
      <ChartTypeToggle value={chartType} onChange={setChartType} />
      {!compact && ticker ? (
        <NameDeskToggle
          open={deskOpen && statementUnderChart}
          onToggle={() => {
            // Book opens widescreen chart + statement under the chart — never an overlay on the desk.
            if (!statementUnderChart) {
              router.push(`/operator/chart?symbol=${encodeURIComponent(ticker)}&desk=1`);
              return;
            }
            setDeskOpen((v) => !v);
          }}
        />
      ) : null}
    </div>
  );

  return (
    <div
      className={clsx(
        "cockpit-panel flex flex-col min-w-0 overflow-hidden",
        compact ? "flex-1 max-h-48" : "min-h-0",
        className,
      )}
    >
      <CockpitPanelHeader
        title={companyName || ticker || "График"}
        subtitle={
          compact
            ? `${t(`chart.tf.${timeframe}`)} · компактный`
            : companyName && ticker && companyName.toUpperCase() !== ticker.toUpperCase()
              ? `${ticker} · онлайн`
              : "онлайн"
        }
        href={chartHref}
        action={headerExtra}
      />

      {showOverlay && !compact && (
        <div className="flex items-center flex-wrap gap-x-4 gap-y-1 px-3 py-1.5 border-b border-cockpit-border bg-cockpit-panel-raised/50 text-[11px]">
          <span className="flex items-center gap-1.5">
            <span className="relative flex h-1.5 w-1.5">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-terminal-up opacity-70" />
              <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-terminal-up" />
            </span>
            <span className="text-qa-muted uppercase tracking-wide text-[9px]">онлайн</span>
          </span>
          {currentPrice != null && (
            <span className="tabular-nums text-qa-text">
              <span className="text-qa-muted">Цена </span>${currentPrice.toFixed(2)}
            </span>
          )}
          {unrealizedPnl != null && (
            <span className={clsx("tabular-nums font-semibold", unrealizedPnl >= 0 ? "text-terminal-up" : "text-terminal-down")}>
              <span className="text-qa-muted font-normal">P&amp;L сейчас </span>{formatUsd(unrealizedPnl)}
            </span>
          )}
          {projectedProfit != null && (
            <span className={clsx("tabular-nums", projectedProfit >= 0 ? "text-terminal-up/90" : "text-terminal-down/90")}>
              <span className="text-qa-muted font-normal">полный результат, если цена дойдёт до цели </span>{formatUsd(projectedProfit)}
              {position!.tp_hit_probability != null && (
                <span className="text-qa-muted font-normal">
                  {" "}
                  (P≈{formatTpHitProbability(position!)})
                </span>
              )}
            </span>
          )}
          {position!.expected_pnl_low != null && position!.expected_pnl_high != null && (
            <span className="tabular-nums text-qa-text">
              <span className="text-qa-muted font-normal">Ожид. </span>
              {formatExpectedPnlRange(position!)}
            </span>
          )}
          {avgEntryPrice != null && (
            <span className="tabular-nums text-qa-text">
              {dualBook && avgLongPrice != null && avgShortPrice != null ? (
                <>
                  <span className="text-qa-muted">Avg↑ </span>${avgLongPrice.toFixed(2)}
                  <span className="text-qa-muted"> · Avg↓ </span>${avgShortPrice.toFixed(2)}
                </>
              ) : (
                <>
                  <span className="text-qa-muted">Avg {netSideLabel} </span>
                  ${avgEntryPrice.toFixed(2)}
                </>
              )}
              {avgZoneHint ? <span className="text-qa-muted"> · {avgZoneHint}</span> : null}
              {fundingHint ? <span className="text-qa-muted">{fundingHint}</span> : null}
              {book?.unrealized_pct != null ? (
                <span
                  className={clsx(
                    "ml-1",
                    book.unrealized_pct >= 0 ? "text-terminal-up" : "text-terminal-down",
                  )}
                >
                  {book.unrealized_pct >= 0 ? "+" : ""}
                  {book.unrealized_pct.toFixed(2)}%
                </span>
              ) : null}
            </span>
          )}
          {robotActive && (
            <span className="inline-flex items-center gap-1 text-sky-400/90 uppercase tracking-wide text-[9px] font-semibold">
              <span className="relative flex h-1.5 w-1.5">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-sky-400 opacity-60" />
                <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-sky-400" />
              </span>
              Робот активен
              {activePlan?.mode ? (
                <span className="text-qa-muted font-normal normal-case tracking-normal">
                  · {activePlan.mode}
                </span>
              ) : null}
            </span>
          )}
          {dualBook && beLong != null ? (
            <span className="tabular-nums text-qa-muted">L-BE ${beLong.toFixed(2)}</span>
          ) : null}
          {dualBook && beShort != null ? (
            <span className="tabular-nums text-qa-muted">S-BE ${beShort.toFixed(2)}</span>
          ) : null}
          {beNet != null ? (
            <span className="tabular-nums text-qa-muted">
              {dualBook ? "Net " : ""}BE ${beNet.toFixed(2)}
            </span>
          ) : null}
          {entryPrice != null && (
            <span className="tabular-nums text-qa-text">
              <span className="text-qa-muted">Вход </span>${entryPrice.toFixed(2)}
            </span>
          )}
          {updatedLabel && (
            <span className="tabular-nums text-qa-muted ml-auto">обновлено {updatedLabel}</span>
          )}
        </div>
      )}

      {!showOverlay && !compact && (avgEntryPrice != null || robotActive) && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-3 py-1.5 border-b border-cockpit-border text-[11px]">
          {avgEntryPrice != null ? (
            <span className="tabular-nums text-qa-text">
              {dualBook && avgLongPrice != null && avgShortPrice != null ? (
                <>
                  <span className="text-qa-muted">Avg↑ </span>${avgLongPrice.toFixed(2)}
                  <span className="text-qa-muted"> · Avg↓ </span>${avgShortPrice.toFixed(2)}
                </>
              ) : (
                <>
                  <span className="text-qa-muted">Avg {netSideLabel} </span>
                  ${avgEntryPrice.toFixed(2)}
                </>
              )}
              {avgZoneHint ? <span className="text-qa-muted"> · {avgZoneHint}</span> : null}
              {lotsHint ? <span className="text-qa-muted">{lotsHint}</span> : null}
              {fundingHint ? <span className="text-qa-muted">{fundingHint}</span> : null}
              {book?.unrealized_usd != null ? (
                <span
                  className={clsx(
                    "ml-2",
                    book.unrealized_usd >= 0 ? "text-terminal-up" : "text-terminal-down",
                  )}
                >
                  {formatUsd(book.unrealized_usd)}
                  {book.unrealized_pct != null
                    ? ` (${book.unrealized_pct >= 0 ? "+" : ""}${book.unrealized_pct.toFixed(2)}%)`
                    : ""}
                </span>
              ) : null}
            </span>
          ) : null}
          {robotActive ? (
            <span className="inline-flex items-center gap-1 text-sky-400/90 uppercase tracking-wide text-[9px] font-semibold">
              <span className="relative flex h-1.5 w-1.5">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-sky-400 opacity-60" />
                <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-sky-400" />
              </span>
              Робот активен
            </span>
          ) : null}
          {dualBook && beLong != null ? (
            <span className="tabular-nums text-qa-muted">L-BE ${beLong.toFixed(2)}</span>
          ) : null}
          {dualBook && beShort != null ? (
            <span className="tabular-nums text-qa-muted">S-BE ${beShort.toFixed(2)}</span>
          ) : null}
          {beNet != null ? (
            <span className="tabular-nums text-qa-muted">
              {dualBook ? "Net " : ""}BE ${beNet.toFixed(2)}
            </span>
          ) : breakevenPrice != null ? (
            <span className="tabular-nums text-qa-muted">BE ${breakevenPrice.toFixed(2)}</span>
          ) : null}
        </div>
      )}

      {!compact && ticker ? (
        <>
          <RobotPanel
            ticker={ticker}
            plan={activePlan}
            entryHint={livePrice ?? (bars?.length ? Number(bars[bars.length - 1]?.close) : null)}
            bars={bars}
            shadowEquity={shadowEquity}
            onShadowEquity={setShadowEquity}
            onChanged={() => {
              void qc.invalidateQueries({ queryKey: ["robot-book", ticker] });
            }}
          />
        </>
      ) : null}

      {!compact && osc && (
        <div
          className="px-3 py-1 border-b border-cockpit-border text-[10px] text-qa-muted truncate shrink-0"
          title={`${osc.heat}; ${osc.impulse}`}
        >
          {osc.heat}; {osc.impulse}
        </div>
      )}

      <div
        ref={chartAreaRef}
        className={clsx(
          "relative flex-1 min-h-[280px] md:min-h-[360px] min-w-0 w-full max-w-full flex flex-col overflow-hidden z-0",
          compact ? "p-2 min-h-[120px]" : "p-3",
        )}
      >
        <ErrorBoundary>
          {!ticker ? (
            <ReasonState
              code="no-symbol"
              title="Символ не выбран"
              detail="Выберите тикер в watchlist слева"
              compact={compact}
              className="h-full min-h-[100px]"
            />
          ) : isLoading ? (
            <ReasonState
              code="loading"
              title="Загрузка котировок…"
              detail={`Запрос баров для ${ticker}`}
              compact={compact}
              className="h-full min-h-[100px]"
            />
          ) : error || !bars?.length ? (
            <ReasonState
              code="no-data"
              title="Нет рыночных данных"
              detail={
                error
                  ? "API market/bars недоступен или тикер не найден"
                  : "Пайплайн данных не вернул бары для выбранного символа"
              }
              compact={compact}
              className="h-full min-h-[100px]"
            />
          ) : chartEngine === "lightweight" || chartType === "candlestick" ? (
            <LightweightChart
              ticker={ticker}
              bars={bars}
              timeframe={timeframe}
              height={chartHeight}
              fillContainer={fixedHeight == null}
              containHeader={fixedHeight != null}
              showVolume={!compact}
              entryPrice={entryPrice}
              avgEntryPrice={avgEntryPrice}
              avgLongPrice={avgLongPrice}
              avgShortPrice={avgShortPrice}
              breakevenPrice={breakevenPrice}
              breakevenLong={dualBook ? beLong : null}
              breakevenShort={dualBook ? beShort : null}
              netBreakeven={beNet}
              strategyLow={strategyLow}
              strategyHigh={strategyHigh}
              stopLoss={stopLoss}
              takeProfit={takeProfit}
              currentPrice={currentPrice}
              livePrice={livePrice}
              freshnessLabel={
                typeof (quote as { freshness_label?: unknown } | undefined)?.freshness_label === "string"
                  ? ((quote as { freshness_label: string }).freshness_label)
                  : null
              }
              tradeMarkers={tradeMarkers}
              robotLevels={robotLevels}
              chartType={chartType}
              onChartTypeChange={setChartType}
              showChartTypeToggle={false}
              className="h-full"
            />
          ) : (
            <PriceChart
              ticker={ticker}
              timeframe={timeframe}
              height={chartHeight}
              showVolume={!compact}
              prefetchBars={bars}
              entryPrice={entryPrice}
              stopLoss={stopLoss}
              takeProfit={takeProfit}
              currentPrice={currentPrice}
              livePrice={livePrice}
              className="h-full"
            />
          )}
        </ErrorBoundary>
      </div>
      {!compact && ticker && statementUnderChart && deskOpen ? (
        <div
          id="ticker-statement"
          className="shrink-0 border-t border-cockpit-border scroll-mt-4"
        >
          <NameDeskCard
            ticker={ticker}
            direction={position?.direction}
            open
            variant="panel"
            onClose={() => setDeskOpen(false)}
          />
        </div>
      ) : null}
    </div>
  );
}
