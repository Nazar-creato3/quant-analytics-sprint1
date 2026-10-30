import type { OHLCVBar } from "@/types";

export function rsi14(bars: OHLCVBar[]): number | null {
  if (bars.length < 15) return null;
  const closes = bars.map((b) => b.close);
  let gain = 0;
  let loss = 0;
  for (let i = 1; i <= 14; i += 1) {
    const d = closes[i] - closes[i - 1];
    if (d >= 0) gain += d;
    else loss -= d;
  }
  let avgGain = gain / 14;
  let avgLoss = loss / 14;
  for (let i = 15; i < closes.length; i += 1) {
    const d = closes[i] - closes[i - 1];
    avgGain = (avgGain * 13 + Math.max(d, 0)) / 14;
    avgLoss = (avgLoss * 13 + Math.max(-d, 0)) / 14;
  }
  if (avgLoss === 0) return 100;
  const rs = avgGain / avgLoss;
  return 100 - 100 / (1 + rs);
}

export function macdHistogram(bars: OHLCVBar[]): number | null {
  if (bars.length < 35) return null;
  const closes = bars.map((b) => b.close);
  const ema = (period: number) => {
    const k = 2 / (period + 1);
    let v = closes[0];
    for (let i = 1; i < closes.length; i += 1) v = closes[i] * k + v * (1 - k);
    return v;
  };
  const line = ema(12) - ema(26);
  return line;
}

export function oscillatorCopy(rsi: number | null, macd: number | null): { heat: string; impulse: string } {
  let heat = "температура обычная";
  if (rsi != null && rsi >= 70) heat = "перегрета";
  else if (rsi != null && rsi <= 30) heat = "переохлаждена";
  let impulse = "импульс ровный";
  if (macd != null && macd > 0) impulse = "импульс ещё в сторону роста";
  else if (macd != null && macd < 0) impulse = "импульс ослаб";
  return { heat, impulse };
}
