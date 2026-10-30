"use client";

import { useEffect, useRef, useMemo, useState, useCallback } from "react";
import {
  ColorType,
  LineStyle,
  createChart,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
} from "lightweight-charts";
import { clsx } from "clsx";
import { TrendingDown, TrendingUp } from "lucide-react";
import type { OHLCVBar, TradeMarker } from "@/types";
import { useChartColors } from "@/hooks/useChartColors";
import { formatInstrumentPrice } from "@/lib/instrument-price-format";
import { toCandlestickData, toLineData, toVolumeData, barTime } from "./ohlcvAdapters";
import { ChartTypeToggle, type ChartDisplayType } from "./ChartTypeToggle";
import { overlayFromAligned, lastLineValue } from "./movingAverages";
import { useChartIndicators } from "./useChartIndicators";

interface LightweightChartProps {
  ticker: string;
  bars: OHLCVBar[];
  timeframe?: "1d" | "1h" | "4h" | "15m" | "5m" | "1w";
  height?: number;
  showVolume?: boolean;
  className?: string;
  entryPrice?: number | null;
  avgEntryPrice?: number | null;
  avgLongPrice?: number | null;
  avgShortPrice?: number | null;
  breakevenPrice?: number | null;
  breakevenLong?: number | null;
  breakevenShort?: number | null;
  netBreakeven?: number | null;
  strategyLow?: number | null;
  strategyHigh?: number | null;
  stopLoss?: number | null;
  takeProfit?: number | null;
  currentPrice?: number | null;
  livePrice?: number | null;
  tradeMarkers?: TradeMarker[];
  /** Extra Robot Core levels (add / trail / plan SL·TP if distinct). */
  robotLevels?: Array<{
    kind: string;
    price: number;
    status?: string;
    title?: string;
  }>;
  isMockData?: boolean;
  dataSource?: string | null;
  chartType?: ChartDisplayType;
  onChartTypeChange?: (type: ChartDisplayType) => void;
  showChartTypeToggle?: boolean;
  containHeader?: boolean;
  fillContainer?: boolean;
  showMovingAverages?: boolean;
  freshnessLabel?: string | null;
}

function formatPrice(v: number, ticker?: string): string {
  // Instrument currency and the full price: LKOH is 6 291,50 ₽, not "$6.3k".
  if (ticker) return formatInstrumentPrice(ticker, v);
  if (v >= 1000) return v.toLocaleString("ru-RU", { maximumFractionDigits: 2 });
  if (v >= 1) return `$${v.toFixed(2)}`;
  return `$${v.toFixed(4)}`;
}

type ChartBundle = {
  chart: IChartApi;
  priceSeries: ISeriesApi<"Candlestick"> | ISeriesApi<"Line">;
  volumeSeries: ISeriesApi<"Histogram"> | null;
  sma20: ISeriesApi<"Line"> | null;
  sma50: ISeriesApi<"Line"> | null;
  ema20: ISeriesApi<"Line"> | null;
  bbUpper: ISeriesApi<"Line"> | null;
  bbLower: ISeriesApi<"Line"> | null;
  vwap: ISeriesApi<"Line"> | null;
  priceLines: IPriceLine[];
  chartType: ChartDisplayType;
};

function applySeriesData(
  bundle: ChartBundle,
  bars: OHLCVBar[],
  timeframe: string,
  chartType: ChartDisplayType,
) {
  if (chartType === "line") {
    (bundle.priceSeries as ISeriesApi<"Line">).setData(toLineData(bars, timeframe));
  } else {
    (bundle.priceSeries as ISeriesApi<"Candlestick">).setData(toCandlestickData(bars, timeframe));
  }
  if (bundle.volumeSeries) {
    bundle.volumeSeries.setData(toVolumeData(bars, timeframe));
  }
}

function applyMovingAverages(
  bundle: ChartBundle,
  overlays: Record<string, (number | null)[]> | undefined,
  bars: OHLCVBar[],
  timeframe: string,
  enabled: { sma20: boolean; sma50: boolean; ema20: boolean; boll: boolean },
) {
  const empty: never[] = [];
  if (bundle.sma20)
    bundle.sma20.setData(
      enabled.sma20 || enabled.boll ? overlayFromAligned(bars, timeframe, overlays?.sma20) : empty,
    );
  if (bundle.sma50)
    bundle.sma50.setData(enabled.sma50 ? overlayFromAligned(bars, timeframe, overlays?.sma50) : empty);
  if (bundle.ema20)
    bundle.ema20.setData(enabled.ema20 ? overlayFromAligned(bars, timeframe, overlays?.ema20) : empty);
  if (bundle.vwap)
    bundle.vwap.setData(
      timeframe !== "1d" && timeframe !== "1w" ? overlayFromAligned(bars, timeframe, overlays?.vwap) : empty,
    );
  if (bundle.bbUpper && bundle.bbLower) {
    if (enabled.boll) {
      bundle.bbUpper.setData(overlayFromAligned(bars, timeframe, overlays?.bb_upper));
      bundle.bbLower.setData(overlayFromAligned(bars, timeframe, overlays?.bb_lower));
    } else {
      bundle.bbUpper.setData(empty);
      bundle.bbLower.setData(empty);
    }
  }
}

function applyOverlays(
  bundle: ChartBundle,
  overlays: { price: number; color: string; title: string; style: LineStyle }[],
) {
  const series = bundle.priceSeries as ISeriesApi<"Candlestick">;
  bundle.priceLines.forEach((line) => series.removePriceLine(line));
  bundle.priceLines = overlays.map((o) =>
    series.createPriceLine({
      price: o.price,
      color: o.color,
      lineWidth: 1,
      lineStyle: o.style,
      axisLabelVisible: true,
      title: o.title,
    }),
  );
}

function snapMarkerTime(at: string, bars: OHLCVBar[], timeframe: string): ReturnType<typeof barTime> | null {
  if (!bars.length) return null;
  const target = Date.parse(at);
  if (!Number.isFinite(target)) return null;
  let best = bars[0]!;
  let bestDist = Math.abs(Date.parse(best.timestamp) - target);
  for (const b of bars) {
    const dist = Math.abs(Date.parse(b.timestamp) - target);
    if (dist < bestDist) {
      best = b;
      bestDist = dist;
    }
  }
  return barTime(best.timestamp, timeframe);
}

function applyTradeMarkers(
  bundle: ChartBundle,
  markers: TradeMarker[],
  bars: OHLCVBar[],
  timeframe: string,
) {
  const series = bundle.priceSeries as ISeriesApi<"Candlestick"> & {
    setMarkers: (m: Array<{
      time: ReturnType<typeof barTime>;
      position: "aboveBar" | "belowBar";
      color: string;
      shape: "arrowUp" | "arrowDown" | "circle";
      text: string;
    }>) => void;
  };
  if (!markers.length) {
    series.setMarkers([]);
    return;
  }

  type Row = {
    time: ReturnType<typeof barTime>;
    position: "aboveBar" | "belowBar";
    color: string;
    shape: "arrowUp" | "arrowDown" | "circle";
    text: string;
    side: string;
    kind: string;
  };

  const mapped: Row[] = [];
  for (const m of markers) {
    const time = snapMarkerTime(m.at, bars, timeframe);
    if (time == null) continue;
    const buy = m.side === "buy";
    mapped.push({
      time,
      position: buy ? "belowBar" : "aboveBar",
      color: buy ? "#22C55E" : "#EF4444",
      shape: buy ? "arrowUp" : "arrowDown",
      text: m.label || (buy ? "B" : "S"),
      side: m.side,
      kind: m.kind,
    });
  }

  // Aggregate same candle + same side+kind into B×N @price (broker desk style).
  const buckets = new Map<string, Row & { count: number; priceHint: string }>();
  for (const row of mapped) {
    const key = `${String(row.time)}|${row.side}|${row.kind}|${row.position}`;
    const prev = buckets.get(key);
    if (prev) {
      prev.count += 1;
      prev.text = `${row.side === "buy" ? "B" : "S"}×${prev.count}`;
    } else {
      buckets.set(key, { ...row, count: 1, priceHint: row.text });
    }
  }

  const out = Array.from(buckets.values()).map((b) => ({
    time: b.time,
    position: b.position,
    color: b.color,
    shape: b.shape,
    text: b.count > 1 ? b.text : b.priceHint,
  }));
  out.sort((a, b) => {
    const ta = typeof a.time === "number" ? a.time : Date.parse(String(a.time));
    const tb = typeof b.time === "number" ? b.time : Date.parse(String(b.time));
    return ta - tb;
  });
  series.setMarkers(out);
}

/** Show the most recent bars at a readable size; older history stays a scroll away. */
const RECENT_BARS: Record<string, number> = { "1m": 90, "5m": 78, "15m": 64, "1h": 56, "4h": 60, "1d": 120, "1w": 104 };

function focusRecent(chart: { timeScale: () => { fitContent: () => void; setVisibleLogicalRange: (r: { from: number; to: number }) => void } }, count: number, timeframe: string) {
  const want = RECENT_BARS[timeframe] ?? 120;
  if (count <= want) {
    chart.timeScale().fitContent();
    return;
  }
  chart.timeScale().setVisibleLogicalRange({ from: count - want, to: count + 1 });
}

export function LightweightChart({
  ticker,
  bars,
  timeframe = "1d",
  height = 320,
  showVolume = true,
  className,
  entryPrice,
  avgEntryPrice,
  avgLongPrice,
  avgShortPrice,
  breakevenPrice,
  breakevenLong,
  breakevenShort,
  netBreakeven,
  strategyLow,
  strategyHigh,
  stopLoss,
  takeProfit,
  currentPrice,
  livePrice,
  tradeMarkers = [],
  robotLevels = [],
  isMockData = false,
  dataSource: _dataSource,
  chartType: chartTypeProp,
  onChartTypeChange,
  showChartTypeToggle = true,
  containHeader = false,
  fillContainer = false,
  showMovingAverages = true,
  freshnessLabel = null,
}: LightweightChartProps) {
  const outerRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const bundleRef = useRef<ChartBundle | null>(null);
  const [internalChartType, setInternalChartType] = useState<ChartDisplayType>("candlestick");
  const chartType = chartTypeProp ?? internalChartType;
  const [maEnabled, setMaEnabled] = useState({ sma20: true, sma50: true, ema20: false, boll: false });
  const hoverPriceEl = useRef<HTMLSpanElement>(null);
  const hoverOhlcEl = useRef<HTMLSpanElement>(null);
  const lastPriceRef = useRef(0);
  const serverIndicators = useChartIndicators(ticker, bars, timeframe ?? "1d", showMovingAverages);
  const overlayValues = serverIndicators.data?.overlays;

  const handleChartTypeChange = (next: ChartDisplayType) => {
    if (onChartTypeChange) onChartTypeChange(next);
    else setInternalChartType(next);
  };

  const first = bars[0]?.close ?? 0;
  const lastBarClose = bars[bars.length - 1]?.close ?? 0;
  const last = livePrice ?? lastBarClose;
  lastPriceRef.current = last;
  const totalReturn = first ? ((last - first) / first) * 100 : 0;
  const positive = last >= first;

  const displayBars = useMemo(() => {
    if (livePrice == null || !bars.length) return bars;
    const prev = bars[bars.length - 1];
    const patched = {
      ...prev,
      close: livePrice,
      high: Math.max(prev.high, livePrice),
      low: Math.min(prev.low, livePrice),
    };
    return [...bars.slice(0, -1), patched];
  }, [bars, livePrice]);

  const chartColors = useChartColors();

  const maLegend = useMemo(() => {
    if (!showMovingAverages || !displayBars.length) return [];
    const rows: { key: string; label: string; color: string; value: number | null }[] = [];
    if (maEnabled.sma20 || maEnabled.boll) {
      rows.push({
        key: "sma20",
        label: "SMA20",
        color: "#F5A623",
        value: lastLineValue(overlayFromAligned(displayBars, timeframe, overlayValues?.sma20)),
      });
    }
    if (maEnabled.sma50) {
      rows.push({
        key: "sma50",
        label: "SMA50",
        color: "#5B8DEF",
        value: lastLineValue(overlayFromAligned(displayBars, timeframe, overlayValues?.sma50)),
      });
    }
    if (maEnabled.ema20) {
      rows.push({
        key: "ema20",
        label: "EMA20",
        color: "#C084FC",
        value: lastLineValue(overlayFromAligned(displayBars, timeframe, overlayValues?.ema20)),
      });
    }
    if (maEnabled.boll) {
      rows.push({
        key: "bb-u",
        label: "BOLL↑",
        color: "#94A3B8",
        value: lastLineValue(overlayFromAligned(displayBars, timeframe, overlayValues?.bb_upper)),
      });
      rows.push({
        key: "bb-l",
        label: "BOLL↓",
        color: "#94A3B8",
        value: lastLineValue(overlayFromAligned(displayBars, timeframe, overlayValues?.bb_lower)),
      });
    }
    return rows;
  }, [displayBars, timeframe, maEnabled, showMovingAverages, overlayValues]);

  const overlays = useMemo(() => {
    const items: { price: number; color: string; title: string; style: LineStyle }[] = [];
    if (strategyLow != null) {
      items.push({ price: strategyLow, color: "#64748B", title: "Зона↓", style: LineStyle.SparseDotted });
    }
    if (strategyHigh != null) {
      items.push({ price: strategyHigh, color: "#64748B", title: "Зона↑", style: LineStyle.SparseDotted });
    }
    if (avgLongPrice != null && avgShortPrice != null) {
      items.push({
        price: avgLongPrice,
        color: "#34D399",
        title: "Avg↑",
        style: LineStyle.Solid,
      });
      items.push({
        price: avgShortPrice,
        color: "#F87171",
        title: "Avg↓",
        style: LineStyle.Solid,
      });
    } else if (avgEntryPrice != null) {
      items.push({
        price: avgEntryPrice,
        color: "#F59E0B",
        title: "Avg",
        style: LineStyle.Solid,
      });
    } else if (entryPrice != null) {
      items.push({ price: entryPrice, color: chartColors.entryLine, title: "Вход", style: LineStyle.Dashed });
    }
    if (entryPrice != null && avgEntryPrice != null && Math.abs(entryPrice - avgEntryPrice) > 1e-6) {
      items.push({ price: entryPrice, color: chartColors.entryLine, title: "Вход", style: LineStyle.Dashed });
    }
    if (breakevenLong != null && Number.isFinite(breakevenLong)) {
      items.push({
        price: breakevenLong,
        color: "#CA8A04",
        title: "L-BE",
        style: LineStyle.Dashed,
      });
    }
    if (breakevenShort != null && Number.isFinite(breakevenShort)) {
      items.push({
        price: breakevenShort,
        color: "#A16207",
        title: "S-BE",
        style: LineStyle.Dashed,
      });
    }
    const bePrimary = netBreakeven ?? breakevenPrice;
    if (
      bePrimary != null &&
      avgEntryPrice != null &&
      Math.abs(bePrimary - avgEntryPrice) > 1e-6 &&
      breakevenLong == null &&
      breakevenShort == null
    ) {
      items.push({ price: bePrimary, color: "#EAB308", title: "BE", style: LineStyle.Dashed });
    } else if (
      bePrimary != null &&
      (breakevenLong != null || breakevenShort != null) &&
      Math.abs(bePrimary - (breakevenLong ?? bePrimary)) > 1e-6 &&
      Math.abs(bePrimary - (breakevenShort ?? bePrimary)) > 1e-6
    ) {
      items.push({ price: bePrimary, color: "#EAB308", title: "Net BE", style: LineStyle.Dashed });
    }
    if (stopLoss != null) {
      items.push({ price: stopLoss, color: chartColors.danger, title: "SL", style: LineStyle.Dashed });
    }
    if (takeProfit != null) {
      items.push({ price: takeProfit, color: chartColors.success, title: "TP", style: LineStyle.Dashed });
    }
    for (const lv of robotLevels) {
      if (!Number.isFinite(lv.price) || lv.price <= 0) continue;
      const kind = (lv.kind || "").toLowerCase();
      // Skip kinds already drawn from book/position overlays
      if (kind === "entry" || kind === "tp" || kind === "sl") continue;
      if (kind === "trail" && (lv.status === "pending" || !lv.price)) continue;
      const color =
        kind === "add" ? "#38BDF8" : kind === "trail" ? "#A78BFA" : "#94A3B8";
      const title =
        lv.title ||
        (kind === "add" ? "Add" : kind === "trail" ? "Trail" : kind.toUpperCase());
      const style =
        lv.status === "filled" || lv.status === "triggered"
          ? LineStyle.Solid
          : kind === "trail"
            ? LineStyle.Dashed
            : LineStyle.Dotted;
      items.push({ price: lv.price, color, title, style });
    }
    if (currentPrice != null) {
      const basis = avgEntryPrice ?? entryPrice;
      items.push({
        price: currentPrice,
        color:
          basis != null && currentPrice >= basis
            ? chartColors.success
            : chartColors.danger,
        title: "Live",
        style: LineStyle.Solid,
      });
    }
    return items;
  }, [
    entryPrice,
    avgEntryPrice,
    avgLongPrice,
    avgShortPrice,
    breakevenPrice,
    breakevenLong,
    breakevenShort,
    netBreakeven,
    strategyLow,
    strategyHigh,
    stopLoss,
    takeProfit,
    currentPrice,
    chartColors,
    robotLevels,
  ]);

  const canvasHeight = fillContainer ? height : Math.max(80, height - (containHeader ? 36 : 0));

  const resizeChart = useCallback(() => {
    const container = containerRef.current;
    const bundle = bundleRef.current;
    if (!container || !bundle) return;

    const nextHeight = fillContainer
      ? Math.max(80, container.clientHeight)
      : canvasHeight;

    bundle.chart.applyOptions({
      width: container.clientWidth,
      height: nextHeight,
    });
  }, [canvasHeight, fillContainer]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const initialHeight = fillContainer
      ? Math.max(80, container.clientHeight || canvasHeight)
      : canvasHeight;

    const chart = createChart(container, {
      width: container.clientWidth,
      height: initialHeight,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: chartColors.textMuted,
        fontSize: 10,
      },
      grid: {
        vertLines: { color: chartColors.gridLine },
        horzLines: { color: chartColors.gridLine },
      },
      rightPriceScale: {
        borderColor: chartColors.border,
        scaleMargins: {
          top: 0.08,
          bottom: showVolume ? 0.22 : 0.04,
        },
      },
      timeScale: {
        borderColor: chartColors.border,
        timeVisible: timeframe !== "1d",
        secondsVisible: false,
      },
      crosshair: {
        vertLine: { color: chartColors.crosshair, labelBackgroundColor: chartColors.crosshairLabel },
        horzLine: { color: chartColors.crosshair, labelBackgroundColor: chartColors.crosshairLabel },
      },
    });

    let priceSeries: ISeriesApi<"Candlestick"> | ISeriesApi<"Line">;
    if (chartType === "line") {
      priceSeries = chart.addLineSeries({
        color: chartColors.success,
        lineWidth: 2,
        priceLineVisible: false,
      });
    } else {
      priceSeries = chart.addCandlestickSeries({
        upColor: chartColors.success,
        downColor: chartColors.danger,
        borderVisible: false,
        wickUpColor: chartColors.success,
        wickDownColor: chartColors.danger,
      });
    }

    let volumeSeries: ISeriesApi<"Histogram"> | null = null;
    if (showVolume) {
      volumeSeries = chart.addHistogramSeries({
        priceFormat: { type: "volume" },
        priceScaleId: "volume",
        lastValueVisible: false,
        priceLineVisible: false,
      });
      chart.priceScale("volume").applyOptions({
        scaleMargins: { top: 0.82, bottom: 0 },
        visible: false,
        borderVisible: false,
      });
    }

    const sma20 = showMovingAverages
      ? chart.addLineSeries({ color: "#F5A623", lineWidth: 1, priceLineVisible: false, lastValueVisible: false })
      : null;
    const sma50 = showMovingAverages
      ? chart.addLineSeries({ color: "#5B8DEF", lineWidth: 1, priceLineVisible: false, lastValueVisible: false })
      : null;
    const ema20 = showMovingAverages
      ? chart.addLineSeries({ color: "#C084FC", lineWidth: 1, lineStyle: LineStyle.Dashed, priceLineVisible: false, lastValueVisible: false })
      : null;
    const bbUpper = showMovingAverages
      ? chart.addLineSeries({
          color: "#94A3B8",
          lineWidth: 1,
          lineStyle: LineStyle.Dotted,
          priceLineVisible: false,
          lastValueVisible: false,
        })
      : null;
    const bbLower = showMovingAverages
      ? chart.addLineSeries({
          color: "#94A3B8",
          lineWidth: 1,
          lineStyle: LineStyle.Dotted,
          priceLineVisible: false,
          lastValueVisible: false,
        })
      : null;

    const vwap =
      timeframe !== "1d" && timeframe !== "1w"
        ? chart.addLineSeries({ color: "#22D3EE", lineWidth: 1, priceLineVisible: false, lastValueVisible: false })
        : null;

    const bundle: ChartBundle = {
      chart,
      priceSeries,
      volumeSeries,
      sma20,
      sma50,
      ema20,
      bbUpper,
      bbLower,
      vwap,
      priceLines: [],
      chartType,
    };
    bundleRef.current = bundle;
    chart.subscribeCrosshairMove((param) => {
      const point = param.seriesData.get(priceSeries) as
        | { open?: number; high?: number; low?: number; close?: number; value?: number }
        | undefined;
      const priceNode = hoverPriceEl.current;
      const ohlcNode = hoverOhlcEl.current;
      if (!point) {
        if (priceNode) priceNode.textContent = formatPrice(lastPriceRef.current, ticker);
        if (ohlcNode) ohlcNode.textContent = "";
        return;
      }
      const close = typeof point.close === "number" ? point.close : point.value;
      if (typeof close === "number" && priceNode) {
        priceNode.textContent = formatPrice(close, ticker);
      }
      if (
        ohlcNode &&
        typeof point.open === "number" &&
        typeof point.high === "number" &&
        typeof point.low === "number" &&
        typeof point.close === "number"
      ) {
        ohlcNode.textContent = `O ${formatPrice(point.open, ticker)}  H ${formatPrice(point.high, ticker)}  L ${formatPrice(point.low, ticker)}  C ${formatPrice(point.close, ticker)}`;
      } else if (ohlcNode) {
        ohlcNode.textContent = "";
      }
    });

    if (displayBars.length) {
      applySeriesData(bundle, displayBars, timeframe, chartType);
      applyMovingAverages(bundle, overlayValues, displayBars, timeframe, maEnabled);
      applyOverlays(bundle, overlays);
      applyTradeMarkers(bundle, tradeMarkers, displayBars, timeframe);
      focusRecent(chart, displayBars.length, timeframe);
    }

    const ro = new ResizeObserver(resizeChart);
    ro.observe(container);
    if (fillContainer && outerRef.current) ro.observe(outerRef.current);

    return () => {
      ro.disconnect();
      chart.remove();
      bundleRef.current = null;
    };
  }, [canvasHeight, showVolume, timeframe, chartType, fillContainer, resizeChart, chartColors, overlayValues, maEnabled]);

  useEffect(() => {
    resizeChart();
  }, [canvasHeight, resizeChart]);

  useEffect(() => {
    const bundle = bundleRef.current;
    if (!bundle || !displayBars.length) return;

    applySeriesData(bundle, displayBars, timeframe, chartType);
    applyMovingAverages(bundle, overlayValues, displayBars, timeframe, maEnabled);
    applyOverlays(bundle, overlays);
    applyTradeMarkers(bundle, tradeMarkers, displayBars, timeframe);
    focusRecent(bundle.chart, displayBars.length, timeframe);
  }, [displayBars, timeframe, chartType, overlays, maEnabled, tradeMarkers, overlayValues]);

  return (
    <div
      ref={outerRef}
      className={clsx(
        "flex flex-col min-h-0 min-w-0 w-full max-w-full",
        fillContainer && "h-full flex-1",
        className,
      )}
      style={!fillContainer && containHeader ? { height, maxHeight: height } : undefined}
    >
      <div className="flex items-center justify-between shrink-0 gap-2 pb-1">
        <div className="flex flex-col min-w-0 gap-0.5">
          <div className="flex items-center gap-2 min-w-0">
            <span ref={hoverPriceEl} className="text-base font-bold text-qa-text tabular-nums">
              {formatPrice(last, ticker)}
            </span>
            {freshnessLabel?.trim() && freshnessLabel.trim() !== "нет данных" ? (
              <span data-testid="quote-freshness" className="text-[10px] text-qa-muted truncate">
                {freshnessLabel.trim()}
              </span>
            ) : null}
            <span
              className={clsx(
                "flex items-center gap-1 text-xs font-semibold whitespace-nowrap",
                positive ? "text-terminal-up" : "text-terminal-down",
              )}
            >
              {positive ? <TrendingUp size={11} /> : <TrendingDown size={11} />}
              {positive ? "+" : ""}
              {totalReturn.toFixed(2)}%
              <span className="font-normal text-qa-muted" title="Изменение цены от первой до последней свечи на графике">
                {timeframe === "1d" && bars.length ? ` за ${bars.length} торг. дн.` : " за период графика"}
              </span>
            </span>
            <span
              ref={hoverOhlcEl}
              className="text-[10px] tabular-nums text-qa-muted truncate min-h-[1rem]"
            />
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {isMockData && (
            <span className="text-[10px] uppercase tracking-wide text-terminal-accent bg-[var(--qa-active)] border border-terminal-accent/40 px-1.5 py-0.5 rounded">
              Пример данных
            </span>
          )}
          {showChartTypeToggle && (
            <ChartTypeToggle value={chartType} onChange={handleChartTypeChange} />
          )}
          {showMovingAverages && (
            <div className="flex flex-wrap items-center justify-end gap-1">
              {(
                [
                  ["sma20", "SMA 20"],
                  ["sma50", "SMA 50"],
                  ["ema20", "EMA 20"],
                  ["boll", "BOLL"],
                ] as const
              ).map(([key, label]) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => setMaEnabled((prev) => ({ ...prev, [key]: !prev[key] }))}
                  className={clsx(
                    "text-[10px] px-1.5 py-0.5 rounded border",
                    maEnabled[key]
                      ? "border-terminal-accent/50 text-terminal-accent"
                      : "border-qa-border text-qa-muted",
                  )}
                >
                  {label}
                </button>
              ))}
            </div>
          )}
          <span className="text-xs text-qa-muted hidden sm:inline">
            {bars.length} {timeframe}
          </span>
        </div>
      </div>
      {maLegend.length > 0 && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 pb-1.5 text-[10px] tabular-nums text-qa-muted">
          {maLegend.map((row) => (
            <span key={row.key} className="inline-flex items-center gap-1">
              <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: row.color }} />
              <span style={{ color: row.color }}>{row.label}</span>
              <span className="text-qa-text">
                {row.value == null ? "—" : formatPrice(row.value, ticker)}
              </span>
            </span>
          ))}
        </div>
      )}

      <div
        ref={containerRef}
        className="w-full max-w-full flex-1 min-h-0"
        style={
          fillContainer
            ? { minHeight: 80 }
            : { height: canvasHeight, maxHeight: canvasHeight, minHeight: canvasHeight }
        }
        aria-label={`${chartType} chart for ${ticker}`}
      />
      <p className="text-[9px] text-qa-muted pt-1 shrink-0">Charts by TradingView</p>
    </div>
  );
}
