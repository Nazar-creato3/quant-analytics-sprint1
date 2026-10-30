"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ColorType,
  LineStyle,
  createChart,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
} from "lightweight-charts";
import { clsx } from "clsx";
import { marketApi } from "@/lib/api";
import type { CockpitLookback, CockpitPriceRange, CockpitVolatilityBands, OHLCVBar } from "@/types";
import { useChartColors } from "@/hooks/useChartColors";
import { chartSymbolForApi } from "@/lib/chartSymbol";
import { readChartColors, type ChartColorPalette } from "@/lib/chartColors";
import { toCandlestickData, toLineData, toVolumeData } from "@/components/charts/ohlcvAdapters";
import { ChartTypeToggle, type ChartDisplayType } from "@/components/charts/ChartTypeToggle";
import { CockpitPanelHeader } from "@/components/operator/CockpitPanelHeader";
import { TradingViewAttribution } from "./TradingViewAttribution";

const LOOKBACKS: CockpitLookback[] = ["1D", "1W", "1M", "3M", "6M", "1Y"];

const LOOKBACK_CONFIG: Record<
  CockpitLookback,
  { timeframe: "5m" | "1h" | "1d"; limit: number; barTf: string }
> = {
  "1D": { timeframe: "1h", limit: 24, barTf: "1h" },
  "1W": { timeframe: "1d", limit: 7, barTf: "1d" },
  "1M": { timeframe: "1d", limit: 22, barTf: "1d" },
  "3M": { timeframe: "1d", limit: 66, barTf: "1d" },
  "6M": { timeframe: "1d", limit: 132, barTf: "1d" },
  "1Y": { timeframe: "1d", limit: 252, barTf: "1d" },
};

const CHART_HEIGHT = 360;

interface AssetCockpitChartProps {
  symbol: string;
  priceRange?: CockpitPriceRange | null;
  volatilityBands?: CockpitVolatilityBands | null;
  livePrice?: number | null;
  dataSource?: string | null;
  /** Expected return interval (p10/p90) for forecast overlay on price chart. */
  returnInterval?: { p10: number; p90: number };
  className?: string;
}

type ChartBundle = {
  chart: IChartApi;
  priceSeries: ISeriesApi<"Candlestick"> | ISeriesApi<"Line">;
  volumeSeries: ISeriesApi<"Histogram"> | null;
  priceLines: IPriceLine[];
  chartType: ChartDisplayType;
};

function applyChartData(
  bundle: ChartBundle,
  bars: OHLCVBar[],
  barTf: string,
  chartType: ChartDisplayType,
  priceRange: CockpitPriceRange | null | undefined,
  volatilityBands: CockpitVolatilityBands | null | undefined,
  returnInterval?: { p10: number; p90: number },
  anchorPrice?: number | null,
  colors: ChartColorPalette = readChartColors(),
) {
  if (chartType === "line") {
    (bundle.priceSeries as ISeriesApi<"Line">).setData(toLineData(bars, barTf));
  } else {
    (bundle.priceSeries as ISeriesApi<"Candlestick">).setData(toCandlestickData(bars, barTf));
  }
  if (bundle.volumeSeries) {
    bundle.volumeSeries.setData(toVolumeData(bars, barTf));
  }

  const series = bundle.priceSeries as ISeriesApi<"Candlestick">;
  bundle.priceLines.forEach((line) => series.removePriceLine(line));

  const overlays: { price: number; color: string; title: string; style: LineStyle }[] = [];
  if (priceRange && Number.isFinite(priceRange.period_high) && Number.isFinite(priceRange.period_low)) {
    overlays.push(
      { price: priceRange.period_high, color: colors.rangeBand, title: "Range H", style: LineStyle.Dashed },
      { price: priceRange.period_low, color: colors.rangeBand, title: "Range L", style: LineStyle.Dashed },
    );
  }
  // GA16-307: do not invent zero vol bands when data is missing.
  if (
    volatilityBands &&
    Number.isFinite(volatilityBands.upper) &&
    Number.isFinite(volatilityBands.mid) &&
    Number.isFinite(volatilityBands.lower) &&
    (volatilityBands.upper !== 0 || volatilityBands.mid !== 0 || volatilityBands.lower !== 0)
  ) {
    overlays.push(
      { price: volatilityBands.upper, color: colors.volBand, title: "Vol +", style: LineStyle.Dotted },
      { price: volatilityBands.mid, color: colors.volMid, title: "Vol μ", style: LineStyle.Solid },
      { price: volatilityBands.lower, color: colors.volBand, title: "Vol −", style: LineStyle.Dotted },
    );
  }

  const basePrice = anchorPrice ?? bars[bars.length - 1]?.close;
  if (returnInterval && basePrice != null) {
    overlays.push(
      {
        price: basePrice * (1 + returnInterval.p10),
        color: colors.forecastBand,
        title: "Fc P10",
        style: LineStyle.Dashed,
      },
      {
        price: basePrice * (1 + returnInterval.p90),
        color: colors.forecastBand,
        title: "Fc P90",
        style: LineStyle.Dashed,
      },
    );
  }

  bundle.priceLines = overlays.map((overlay) =>
    series.createPriceLine({
      price: overlay.price,
      color: overlay.color,
      lineWidth: 1,
      lineStyle: overlay.style,
      axisLabelVisible: true,
      title: overlay.title,
    }),
  );

  bundle.chart.timeScale().fitContent();
}

export function AssetCockpitChart({
  symbol,
  priceRange,
  volatilityBands,
  livePrice,
  dataSource: _dataSource,
  returnInterval,
  className,
}: AssetCockpitChartProps) {
  const [lookback, setLookback] = useState<CockpitLookback>("3M");
  const [chartType, setChartType] = useState<ChartDisplayType>("candlestick");
  const config = LOOKBACK_CONFIG[lookback];
  const containerRef = useRef<HTMLDivElement>(null);
  const bundleRef = useRef<ChartBundle | null>(null);
  const chartColors = useChartColors();

  const { data: bars, isLoading, error, isFetched } = useQuery<OHLCVBar[]>({
    queryKey: ["cockpit-bars", symbol, lookback],
    queryFn: () => marketApi.getBars(symbol, config.timeframe, config.limit),
    staleTime: 30_000,
    enabled: !!symbol,
    retry: 1,
    refetchOnMount: "always",
  });

  const displayBars = useMemo(() => {
    if (!bars?.length) return [];
    if (livePrice == null) return bars;
    const prev = bars[bars.length - 1];
    const patched = {
      ...prev,
      close: livePrice,
      high: Math.max(prev.high, livePrice),
      low: Math.min(prev.low, livePrice),
    };
    return [...bars.slice(0, -1), patched];
  }, [bars, livePrice]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || !displayBars.length) return;

    const chart = createChart(container, {
      width: container.clientWidth,
      height: CHART_HEIGHT,
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
        scaleMargins: { top: 0.08, bottom: 0.28 },
      },
      timeScale: {
        borderColor: chartColors.border,
        timeVisible: config.barTf !== "1d",
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

    const volumeSeries = chart.addHistogramSeries({
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
    });
    chart.priceScale("volume").applyOptions({
      scaleMargins: { top: 0.78, bottom: 0 },
    });

    const bundle: ChartBundle = {
      chart,
      priceSeries,
      volumeSeries,
      priceLines: [],
      chartType,
    };
    bundleRef.current = bundle;

    applyChartData(
      bundle,
      displayBars,
      config.barTf,
      chartType,
      priceRange,
      volatilityBands,
      returnInterval,
      livePrice ?? displayBars[displayBars.length - 1]?.close,
      chartColors,
    );

    const ro = new ResizeObserver(() => {
      if (!containerRef.current) return;
      chart.applyOptions({ width: containerRef.current.clientWidth, height: CHART_HEIGHT });
    });
    ro.observe(container);

    return () => {
      ro.disconnect();
      chart.remove();
      bundleRef.current = null;
    };
  }, [displayBars, config.barTf, chartType, priceRange, volatilityBands, returnInterval, livePrice, chartColors]);

  return (
    <div className={clsx("cockpit-panel flex flex-col min-h-0", className)}>
      <CockpitPanelHeader
        title="Price Action"
        subtitle={`${chartType === "line" ? "Line" : "Candlestick"} · ${lookback}`}
      />
      <div className="flex items-center gap-1 px-3 py-2 border-b border-cockpit-border bg-cockpit-panel-raised/40 flex-wrap">
        {LOOKBACKS.map((item) => (
          <button
            key={item}
            type="button"
            onClick={() => setLookback(item)}
            className={clsx(
              "px-2 py-0.5 rounded text-[10px] font-mono font-semibold uppercase tracking-wide transition-colors",
              lookback === item
                ? "bg-primary/20 text-primary border border-primary/40"
                : "text-qa-muted hover:text-qa-text border border-transparent",
            )}
          >
            {item}
          </button>
        ))}
        <div className="ml-auto flex items-center gap-3 text-[10px] font-mono tabular-nums">
          <ChartTypeToggle value={chartType} onChange={setChartType} />
          {priceRange && Number.isFinite(priceRange.range_pct) ? (
            <span className="text-qa-muted">Диапазон {priceRange.range_pct.toFixed(1)}%</span>
          ) : null}
          {volatilityBands &&
          Number.isFinite(volatilityBands.realized_vol) &&
          volatilityBands.realized_vol !== 0 ? (
            <span className="text-qa-muted">Колебания {volatilityBands.realized_vol.toFixed(2)}</span>
          ) : null}
        </div>
      </div>

      <div className="p-3 shrink-0 min-w-0 w-full max-w-full overflow-hidden">
        {isLoading && !displayBars.length ? (
          <div className="skeleton rounded" style={{ height: CHART_HEIGHT }} />
        ) : error || (!displayBars.length && isFetched) ? (
          <div
            className="flex items-center justify-center text-xs text-qa-muted border border-dashed border-cockpit-border rounded"
            style={{ height: CHART_HEIGHT }}
          >
            No OHLCV data for {symbol} ({lookback})
          </div>
        ) : (
          <div
            ref={containerRef}
            className="w-full max-w-full overflow-hidden"
            style={{ height: CHART_HEIGHT, maxHeight: CHART_HEIGHT, minHeight: CHART_HEIGHT }}
            aria-label={`Cockpit chart ${symbol}`}
          />
        )}
      </div>

      <div className="px-3 pb-2 pt-1 border-t border-cockpit-border">
        <TradingViewAttribution />
      </div>
    </div>
  );
}
