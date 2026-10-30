import { format, parseISO } from "date-fns";
import type { CandlestickData, HistogramData, LineData, Time, UTCTimestamp } from "lightweight-charts";
import type { OHLCVBar } from "@/types";
import { CHART_COLORS } from "@/lib/chartColors";

export function barTime(timestamp: string, timeframe: string): Time {
  const d = parseISO(timestamp);
  if (timeframe === "1d") {
    return format(d, "yyyy-MM-dd");
  }
  return Math.floor(d.getTime() / 1000) as UTCTimestamp;
}

export function toCandlestickData(bars: OHLCVBar[], timeframe: string): CandlestickData[] {
  return bars.map((b) => ({
    time: barTime(b.timestamp, timeframe),
    open: b.open,
    high: b.high,
    low: b.low,
    close: b.close,
  }));
}

export function toVolumeData(bars: OHLCVBar[], timeframe: string): HistogramData[] {
  return bars.map((b) => ({
    time: barTime(b.timestamp, timeframe),
    value: b.volume,
    color: b.close >= b.open ? CHART_COLORS.volumeUp : CHART_COLORS.volumeDown,
  }));
}

export function toLineData(bars: OHLCVBar[], timeframe: string): LineData[] {
  return bars.map((b) => ({
    time: barTime(b.timestamp, timeframe),
    value: b.close,
  }));
}

/** Seed prices for common watchlist tickers (used only by mock fallback). */
const MOCK_SEED: Record<string, number> = {
  SPY: 520,
  QQQ: 440,
  AAPL: 190,
  MSFT: 420,
  GOOGL: 175,
  NVDA: 880,
  META: 520,
  AMZN: 185,
  GLD: 220,
  "BTC-USD": 65000,
};

/**
 * TODO: Remove when `/market/bars/{ticker}` is reliably available in all environments.
 * Synthetic OHLCV used only when the live API returns no data or errors.
 */
export function generateMockBars(ticker: string, count = 120): OHLCVBar[] {
  const bars: OHLCVBar[] = [];
  let close = MOCK_SEED[ticker] ?? 100;
  const now = Date.now();

  for (let i = count - 1; i >= 0; i--) {
    const dayMs = now - i * 86_400_000;
    const drift = (Math.random() - 0.48) * (close * 0.012);
    const open = close;
    close = Math.max(0.01, open + drift);
    const high = Math.max(open, close) + Math.random() * close * 0.006;
    const low = Math.min(open, close) - Math.random() * close * 0.006;

    bars.push({
      ticker,
      timestamp: new Date(dayMs).toISOString(),
      timeframe: "1d",
      open: Number(open.toFixed(2)),
      high: Number(high.toFixed(2)),
      low: Number(low.toFixed(2)),
      close: Number(close.toFixed(2)),
      volume: Math.floor(8_000_000 + Math.random() * 12_000_000),
      vwap: null,
    });
  }

  return bars;
}
