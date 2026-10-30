/**
 * User-facing copy for identifiers that exist internally as snake_case keys.
 * Internal names stay in logs / admin views; this module is the only path
 * those strings should take before rendering in the client UI.
 */

const MODEL_LABELS: Record<string, string> = {
  chronos_t5_tiny: "Краткосрочная модель",
  "chronos-t5-tiny": "Краткосрочная модель",
  "amazon/chronos-t5-tiny": "Краткосрочная модель",
  chronos: "Краткосрочная модель",
  direction_lgbm: "Модель направления",
  lightgbm: "Модель направления",
  lgbm: "Модель направления",
  heuristic: "Базовая оценка",
  ensemble: "Ансамбль моделей",
  stacking: "Ансамбль моделей",
  meta_model: "Ансамбль моделей",
  bocpd: "Детектор смены режима",
  aci: "Интервал неопределённости",
  forecastengine: "Прогнозный движок",
  regimeengine: "Оценка режима",
};

const METRIC_LABELS: Record<string, string> = {
  regime_match_accuracy: "Точность модели",
  direction_accuracy: "Точность направления",
  aggregate_calibration_error: "Ошибка калибровки",
  calibration_error: "Ошибка калибровки",
  mae: "Средняя ошибка",
  mape: "Средняя ошибка, %",
  brier_score: "Ошибка вероятностей",
  sample_size: "Число наблюдений",
  expected_return: "Ожидаемая доходность",
  weight: "Вес в прогнозе",
  window_days: "Окно",
  n: "Число наблюдений",
};

const SOURCE_LABELS: Record<string, string> = {
  alpaca_nbbo_iex: "NYSE",
  alpaca_nbbo: "NYSE",
  alpaca_iex: "NYSE",
  alpaca_sip: "NYSE / Nasdaq",
  alpaca: "NYSE / Nasdaq",
  iex: "NYSE",
  nbbo: "NYSE",
  moex_iss: "MOEX",
  moex: "MOEX",
  binance: "Binance",
  ccxt_binance: "Binance",
  okx: "OKX",
  bybit: "Bybit",
  tinkoff: "Т-Банк",
  tbank: "Т-Банк",
  finam: "Финам",
  marketstack: "Биржевые данные",
  finnhub: "Рыночные данные",
  twelve_data: "Рыночные данные",
  twelvedata: "Рыночные данные",
  yfinance: "Рыночные данные",
};

const ORDER_STATUS_LABELS: Record<string, string> = {
  cancelled: "Отменён",
  canceled: "Отменён",
  rejected: "Отклонён",
  expired: "Истёк",
  filled: "Исполнен",
  executed: "Исполнен",
  done: "Исполнен",
  submitted: "Отправлен",
  new: "Отправлен",
  accepted: "Отправлен",
  open: "Отправлен",
  pending: "Отправлен",
  watching: "Отправлен",
  partial: "Частично исполнен",
  partially_filled: "Частично исполнен",
};

function norm(raw: string | null | undefined): string {
  return String(raw ?? "")
    .trim()
    .toLowerCase()
    .replace(/[\s./-]+/g, "_");
}

function lookup(map: Record<string, string>, raw: string | null | undefined): string | null {
  if (raw == null) return null;
  const trimmed = String(raw).trim();
  if (!trimmed) return null;
  return map[trimmed] ?? map[norm(trimmed)] ?? map[trimmed.toLowerCase()] ?? null;
}

/** True when a string looks like an internal identifier, not a human sentence. */
export function looksTechnical(raw: string | null | undefined): boolean {
  const s = String(raw ?? "").trim();
  if (!s) return false;
  if (s.includes(" ")) return false;
  if (/^[a-z][a-z0-9]*(_[a-z0-9]+)+$/i.test(s)) return true;
  if (/^[a-z0-9]+-[a-z0-9-]+$/i.test(s) && s.includes("-")) return true;
  if (s.includes("/") && /[a-z]/.test(s) && /[0-9_]/.test(s)) return true;
  return false;
}

export function labelModel(raw: string | null | undefined): string {
  const hit = lookup(MODEL_LABELS, raw);
  if (hit) return hit;
  const s = String(raw ?? "").trim();
  if (!s) return "Модель";
  if (!looksTechnical(s)) return s;
  return "Прогнозная модель";
}

export function labelMetric(raw: string | null | undefined): string {
  const hit = lookup(METRIC_LABELS, raw);
  if (hit) return hit;
  const s = String(raw ?? "").trim();
  if (!s) return "Показатель";
  if (!looksTechnical(s)) return s;
  return s.replace(/_/g, " ");
}

export function labelSource(raw: string | null | undefined): string {
  const hit = lookup(SOURCE_LABELS, raw);
  if (hit) return hit;
  const s = String(raw ?? "").trim();
  if (!s) return "Биржевые данные";
  if (!looksTechnical(s)) return s;
  const last = s.split(/[/_]/).filter(Boolean).pop() ?? s;
  if (last.toLowerCase() === "iex") return "NYSE";
  return "Источник данных";
}

export function labelOrderStatus(raw: string | null | undefined): string {
  const hit = lookup(ORDER_STATUS_LABELS, raw);
  if (hit) return hit;
  const s = String(raw ?? "").trim();
  return s && !looksTechnical(s) ? s : "В обработке";
}

/** Dispatch: model / source / metric / generic technical id. */
export function labelTechnical(raw: string | null | undefined): string {
  const s = String(raw ?? "").trim();
  if (!s) return "—";
  return (
    lookup(MODEL_LABELS, s) ??
    lookup(METRIC_LABELS, s) ??
    lookup(SOURCE_LABELS, s) ??
    lookup(ORDER_STATUS_LABELS, s) ??
    (looksTechnical(s) ? labelMetric(s) : s)
  );
}

export function formatAccuracyPct(value: number | null | undefined): string {
  if (value == null || Number.isNaN(Number(value))) return "—";
  const n = Number(value);
  const pct = n <= 1 ? n * 100 : n;
  return `${pct.toFixed(0)}%`;
}

export function formatMetricLine(
  key: string,
  value: number | null | undefined,
  { asPercent = key.includes("accuracy") } = {},
): string {
  const label = labelMetric(key);
  if (value == null || Number.isNaN(Number(value))) return `${label}: —`;
  if (asPercent) return `${label}: ${formatAccuracyPct(value)}`;
  const n = Number(value);
  return `${label}: ${n.toFixed(n >= 1 ? 2 : 3)}`;
}
