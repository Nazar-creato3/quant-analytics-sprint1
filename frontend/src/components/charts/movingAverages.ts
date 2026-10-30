import type { LineData } from "lightweight-charts";
import type { OHLCVBar } from "@/types";
import { barTime } from "./ohlcvAdapters";

/** Map server overlay values (aligned with bars) onto lightweight-charts points. */
export function overlayFromAligned(
  bars: OHLCVBar[],
  timeframe: string,
  values: (number | null)[] | undefined,
): LineData[] {
  const data: LineData[] = [];
  if (!values) return data;
  for (let i = 0; i < bars.length; i += 1) {
    const v = values[i];
    if (v == null || !Number.isFinite(v)) continue;
    data.push({ time: barTime(bars[i].timestamp, timeframe), value: v });
  }
  return data;
}

export function lastLineValue(data: LineData[]): number | null {
  if (!data.length) return null;
  const value = data[data.length - 1]?.value;
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}
