"use client";

import { useState, useEffect, useMemo, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { marketApi } from "@/lib/api";
import { QUOTE_POLL_MS } from "@/lib/marketPoll";
import { OHLCVBar } from "@/types";
import {
  AreaChart, Area, BarChart, Bar,
  XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine,
} from "recharts";
import { format, parseISO } from "date-fns";
import { clsx } from "clsx";
import { useChartColors } from "@/hooks/useChartColors";
import { TrendingUp, TrendingDown, RefreshCw } from "lucide-react";
import { Skeleton } from "@/components/ui";

interface PriceChartProps {
  ticker: string;
  timeframe?: "1d" | "1h" | "4h" | "15m" | "5m" | "1w";
  height?: number;
  showVolume?: boolean;
  className?: string;
  /** Skip internal fetch when bars are already loaded upstream */
  prefetchBars?: OHLCVBar[];
  /** Optional position overlay lines (entry / stop-loss / take-profit / live price) */
  entryPrice?: number | null;
  stopLoss?: number | null;
  takeProfit?: number | null;
  currentPrice?: number | null;
  /** Live spot quote — overrides header price when fresher than last bar close */
  livePrice?: number | null;
}

interface ChartPoint {
  ts: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  label: string;
}

function formatPrice(v: number): string {
  if (v >= 1000) return `$${(v / 1000).toFixed(1)}k`;
  if (v >= 1)    return `$${v.toFixed(2)}`;
  return `$${v.toFixed(4)}`;
}

function formatVolume(v: number): string {
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000)     return `${(v / 1_000).toFixed(0)}K`;
  return `${v}`;
}

const CustomTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload as ChartPoint;
  const change = ((d.close - d.open) / d.open) * 100;
  const positive = d.close >= d.open;

  return (
    <div className="bg-qa-panel-secondary border border-qa-border-strong rounded-lg p-3 text-xs">
      <div className="font-semibold text-qa-text mb-2">{d.label}</div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-1">
        <span className="text-qa-muted">Открытие</span>
        <span className="text-qa-text tabular-nums text-right">{formatPrice(d.open)}</span>
        <span className="text-qa-muted">Макс.</span>
        <span className="text-terminal-up tabular-nums text-right">{formatPrice(d.high)}</span>
        <span className="text-qa-muted">Мин.</span>
        <span className="text-terminal-down tabular-nums text-right">{formatPrice(d.low)}</span>
        <span className="text-qa-muted">Закрытие</span>
        <span className={clsx("font-semibold tabular-nums text-right", positive ? "text-terminal-up" : "text-terminal-down")}>
          {formatPrice(d.close)}
        </span>
        <span className="text-qa-muted">Изменение</span>
        <span className={clsx("tabular-nums text-right", positive ? "text-terminal-up" : "text-terminal-down")}>
          {positive ? "+" : ""}{change.toFixed(2)}%
        </span>
        <span className="text-qa-muted">Объём</span>
        <span className="text-qa-muted tabular-nums text-right">{formatVolume(d.volume)}</span>
      </div>
    </div>
  );
};

export function PriceChart({
  ticker,
  timeframe = "1d",
  height = 240,
  showVolume = true,
  className,
  prefetchBars,
  entryPrice,
  stopLoss,
  takeProfit,
  currentPrice,
  livePrice,
}: PriceChartProps) {
  const colors = useChartColors();
  const { data: fetchedBars, isLoading, error, refetch } = useQuery<OHLCVBar[]>({
    queryKey: ["bars", ticker, timeframe],
    queryFn: () => marketApi.getBars(ticker, timeframe, 120),
    staleTime: 60_000,
    enabled: !!ticker && !prefetchBars,
  });

  const bars = prefetchBars ?? fetchedBars;
  const loading = !prefetchBars && isLoading;

  const chartData: ChartPoint[] = useMemo(() => {
    if (!bars?.length) return [];
    const mapped = bars.map((b) => ({
      ts: b.timestamp,
      open: b.open,
      high: b.high,
      low: b.low,
      close: b.close,
      volume: b.volume,
      label: format(
        parseISO(b.timestamp),
        timeframe === "1d" ? "dd MMM yy" : "dd MMM HH:mm"
      ),
    }));
    if (livePrice != null && mapped.length) {
      const last = mapped[mapped.length - 1];
      mapped[mapped.length - 1] = {
        ...last,
        close: livePrice,
        high: Math.max(last.high, livePrice),
        low: Math.min(last.low, livePrice),
      };
    }
    return mapped;
  }, [bars, livePrice, timeframe]);

  if (loading) {
    return (
      <div className={clsx("space-y-2", className)}>
        <Skeleton className={`h-${Math.round(height / 4)}`} />
        <Skeleton className="h-3 w-1/2" />
      </div>
    );
  }

  if (error || !chartData.length) {
    return (
      <div className={clsx(
        "flex flex-col items-center justify-center border border-dashed border-qa-border rounded-lg text-qa-muted text-xs gap-2",
        className
      )}
        style={{ height }}
      >
        <span>Нет данных для {ticker}</span>
        <button onClick={() => refetch()} className="btn-ghost py-1 text-xs">
          <RefreshCw size={11} /> Обновить
        </button>
      </div>
    );
  }

  // chartData built above (includes live price patch)

  const first = chartData[0].close;
  const lastBarClose = chartData[chartData.length - 1].close;
  const last = livePrice ?? lastBarClose;
  const totalReturn = ((last - first) / first) * 100;
  const positive = last >= first;

  const priceColor = positive ? colors.success : colors.danger;
  const volHeight = showVolume ? Math.round(height * 0.28) : 0;
  const chartHeight = height - volHeight - (showVolume ? 8 : 0);

  // Overlay levels (entry / SL / TP / live price) — extend domain so lines stay visible.
  const overlays: { value: number; color: string; label: string; dash?: string }[] = [];
  if (entryPrice != null) {
    overlays.push({ value: entryPrice, color: colors.entryLine, label: "Вход", dash: "5 3" });
  }
  if (stopLoss != null) {
    overlays.push({ value: stopLoss, color: colors.danger, label: "SL", dash: "5 3" });
  }
  if (takeProfit != null) {
    overlays.push({ value: takeProfit, color: colors.success, label: "TP", dash: "5 3" });
  }
  const liveColor =
    currentPrice != null && entryPrice != null
      ? currentPrice >= entryPrice
        ? colors.success
        : colors.danger
      : colors.liveNeutral;

  // Domain with padding, widened to include overlay levels
  const allCloses = chartData.map(d => d.close);
  const domainValues = [
    ...allCloses,
    ...overlays.map(o => o.value),
    ...(currentPrice != null ? [currentPrice] : []),
  ];
  const minClose = Math.min(...domainValues);
  const maxClose = Math.max(...domainValues);
  const pad = (maxClose - minClose) * 0.08 || maxClose * 0.02;
  const yMin = minClose - pad;
  const yMax = maxClose + pad;

  return (
    <div className={clsx("space-y-0", className)}>
      {/* Header stat row */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="text-base font-bold text-qa-text tabular-nums">{formatPrice(last)}</span>
          <span className={clsx(
            "flex items-center gap-1 text-xs font-semibold",
            positive ? "text-terminal-up" : "text-terminal-down"
          )}>
            {positive ? <TrendingUp size={11} /> : <TrendingDown size={11} />}
            {positive ? "+" : ""}{totalReturn.toFixed(2)}%
          </span>
        </div>
        <span className="text-xs text-qa-muted">{chartData.length} баров · {timeframe}</span>
      </div>

      {/* Price area chart */}
      <ResponsiveContainer width="100%" height={chartHeight}>
        <AreaChart data={chartData} margin={{ top: 4, right: 0, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id={`grad-${ticker}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%"  stopColor={priceColor} stopOpacity={0.20} />
              <stop offset="95%" stopColor={priceColor} stopOpacity={0.01} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke={colors.gridLine} vertical={false} />
          <XAxis
            dataKey="label"
            tick={{ fontSize: 9, fill: colors.crosshair }}
            tickLine={false}
            axisLine={false}
            interval="preserveStartEnd"
          />
          <YAxis
            domain={[yMin, yMax]}
            tickFormatter={formatPrice}
            tick={{ fontSize: 9, fill: colors.crosshair }}
            tickLine={false}
            axisLine={false}
            width={54}
          />
          <Tooltip content={<CustomTooltip />} />
          <ReferenceLine
            y={first}
            stroke={colors.border}
            strokeDasharray="4 4"
            strokeWidth={1}
          />
          {overlays.map(o => (
            <ReferenceLine
              key={o.label}
              y={o.value}
              stroke={o.color}
              strokeDasharray={o.dash}
              strokeWidth={1}
              strokeOpacity={0.85}
              label={{
                value: `${o.label} ${formatPrice(o.value)}`,
                position: "right",
                fill: o.color,
                fontSize: 9,
              }}
            />
          ))}
          {currentPrice != null && (
            <ReferenceLine
              y={currentPrice}
              stroke={liveColor}
              strokeWidth={1.25}
              label={{
                value: formatPrice(currentPrice),
                position: "insideRight",
                fill: liveColor,
                fontSize: 9,
                fontWeight: 600,
              }}
            />
          )}
          <Area
            type="monotone"
            dataKey="close"
            stroke={priceColor}
            strokeWidth={1.5}
            fill={`url(#grad-${ticker})`}
            dot={false}
            activeDot={{ r: 3, fill: priceColor, strokeWidth: 0 }}
          />
        </AreaChart>
      </ResponsiveContainer>

      {/* Volume bars */}
      {showVolume && (
        <ResponsiveContainer width="100%" height={volHeight}>
          <BarChart data={chartData} margin={{ top: 0, right: 0, bottom: 0, left: 0 }}>
            <XAxis dataKey="label" hide />
            <YAxis hide />
            <Bar
              dataKey="volume"
              fill={colors.volumeBar}
              radius={[1, 1, 0, 0]}
              maxBarSize={12}
            />
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}


// ── Multi-ticker sparklines row ───────────────────────────────────────────────

interface SparklineProps {
  ticker: string;
  onClick?: () => void;
  isSelected?: boolean;
  /** Stagger fetch on detail pages to avoid burst load */
  index?: number;
}

export function TickerSparkline({
  ticker,
  onClick,
  isSelected,
  index = 0,
}: SparklineProps) {
  const colors = useChartColors();
  const [fetchEnabled, setFetchEnabled] = useState(isSelected);

  useEffect(() => {
    if (isSelected) {
      setFetchEnabled(true);
      return;
    }
    const timer = setTimeout(() => setFetchEnabled(true), index * 450);
    return () => clearTimeout(timer);
  }, [isSelected, index]);

  const quoteForceRef = useRef(true);

  useEffect(() => {
    quoteForceRef.current = true;
  }, [ticker]);

  const { data: bars, isLoading } = useQuery<OHLCVBar[]>({
    queryKey: ["bars", ticker, "1d", "sparkline"],
    queryFn: () => marketApi.getBars(ticker, "1d", 30),
    staleTime: 120_000,
    enabled: fetchEnabled,
    retry: 1,
  });

  const { data: quote } = useQuery({
    queryKey: ["quote", ticker, "sparkline"],
    queryFn: () => {
      const force = quoteForceRef.current;
      quoteForceRef.current = false;
      return marketApi.getQuote(ticker, { forceRefresh: force });
    },
    staleTime: QUOTE_POLL_MS,
    refetchInterval: QUOTE_POLL_MS,
    enabled: fetchEnabled,
    retry: 1,
  });

  if (!fetchEnabled || isLoading) {
    return (
      <div className="w-full h-12 skeleton rounded" />
    );
  }

  if (!bars?.length) return null;

  const lastBarClose = bars[bars.length - 1].close;
  const livePrice = typeof quote?.price === "number" ? quote.price : lastBarClose;
  const first = bars[0].close;
  const change = ((livePrice - first) / first) * 100;
  const positive = change >= 0;
  const color = positive ? colors.success : colors.danger;

  const data = bars.map(b => ({ v: b.close }));

  return (
    <button
      onClick={onClick}
      className={clsx(
        "flex items-center gap-3 w-full px-3 py-2 rounded-lg border transition-all text-left",
        isSelected
          ? "bg-primary/20 border-primary/40"
          : "bg-cockpit-surface/50 border-cockpit-border hover:border-cockpit-border-strong"
      )}
    >
      <div className="w-12 shrink-0">
        <div className="text-xs font-mono font-bold text-qa-text">{ticker}</div>
        <div className={clsx("text-[10px] font-semibold", positive ? "text-terminal-up" : "text-terminal-down")}>
          {positive ? "+" : ""}{change.toFixed(2)}%
        </div>
      </div>

      <div className="flex-1 h-8">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 2, right: 0, bottom: 2, left: 0 }}>
            <defs>
              <linearGradient id={`sg-${ticker}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%"  stopColor={color} stopOpacity={0.3} />
                <stop offset="95%" stopColor={color} stopOpacity={0} />
              </linearGradient>
            </defs>
            <Area
              type="monotone"
              dataKey="v"
              stroke={color}
              strokeWidth={1.2}
              fill={`url(#sg-${ticker})`}
              dot={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      <div className="text-right shrink-0">
        <div className="text-xs font-mono text-qa-text">{formatPrice(livePrice)}</div>
      </div>
    </button>
  );
}
