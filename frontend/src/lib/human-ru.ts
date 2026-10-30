import type { Maneuver } from "@/types";

export const STRATEGY_LABEL_RU: Record<string, string> = {
  momentum: "импульс",
  mean_reversion: "возврат к среднему",
  breakout: "пробой",
  grid: "сетка",
  event_driven: "событие",
  trend_following: "тренд",
  macro: "общий рынок",
  no_trade: "сейчас не входим",
};

export const STATUS_LABEL_RU: Record<string, string> = {
  pending: "ждёт решения",
  pending_approval: "ждёт решения",
  awaiting_approval: "ждёт решения",
  approved: "одобрена",
  rejected: "отклонена",
  executing: "отправляем на биржу",
  filled: "сделка прошла",
  cancelled: "отменена",
  invalidated: "снята",
  closed: "закрыта",
  open: "открыта",
  active: "активна",
  paused: "на паузе",
  expired: "истекла",
  failed: "не прошла",
  error: "ошибка",
  submitted: "отправлена",
  queued: "в очереди",
  new: "новая",
  draft: "черновик",
  executed: "исполнена",
  partially_filled: "исполнена частично",
  partial: "частично",
  done: "готово",
  completed: "завершена",
  edited: "изменена",
  approved_pending_execution: "одобрена, ждёт исполнения",
};

function softFallback(value: string): string {
  // Never show an internal code like "pending_risk_check" to the user.
  return /^[a-z0-9]+(_[a-z0-9]+)+$/i.test(value) || /^[a-z]+$/.test(value) ? "—" : value;
}

export function strategyLabelRu(value: string | undefined | null): string {
  if (!value) return "—";
  return STRATEGY_LABEL_RU[value] ?? STRATEGY_LABEL_RU[value.toLowerCase()] ?? softFallback(value);
}

export function statusLabelRu(value: string | undefined | null): string {
  if (!value) return "—";
  return STATUS_LABEL_RU[value] ?? STATUS_LABEL_RU[value.toLowerCase()] ?? softFallback(value);
}

export function directionLabelRu(value: string | undefined): string {
  if (value === "long") return "покупка";
  if (value === "short") return "продажа";
  return "без стороны";
}

export function bookLabelRu(mode: string | undefined): string {
  return mode === "live" ? "Live-счёт" : "бумага";
}

/** Paper without fill vs live without fill are different truths. */
export function positionTruthRu(m: Pick<Maneuver, "trading_mode" | "status" | "fill_price">): string {
  const live = m.trading_mode === "live";
  const filled = m.status === "filled" || (typeof m.fill_price === "number" && m.fill_price > 0);
  if (live && filled) return "Live-счёт, сделка прошла";
  if (live && !filled) return "Live-ордер, сделка ещё не прошла";
  if (!live && filled) return "бумажная позиция, вход зафиксирован";
  return "на бумаге, вход ещё не зафиксирован";
}

export function exitReasonRu(
  reason: string | null | undefined,
  fillPrice: number | null | undefined,
  exitPrice?: number | null,
): string {
  const filled = typeof fillPrice === "number" && fillPrice > 0;
  const exited = typeof exitPrice === "number" && exitPrice > 0;
  if (reason === "expiration_unfilled") return "срок вышел, ордер сняли — сделки не было";
  if (reason === "expiration") {
    if (filled || exited) return "срок идеи вышел, позицию закрыли по рынку";
    return "срок вышел — вход так и не зафиксировали";
  }
  if (reason === "manual") return "закрыли вручную";
  if (reason === "stop") return "сработал защитный стоп";
  if (reason === "take_profit") return "дошли до цели";
  return reason ? "закрыта" : "—";
}

export function closedPriceLabelRu(m: {
  fill_price?: number | null;
  exit_price?: number | null;
  entry_price?: number | null;
}): string {
  const exit = typeof m.exit_price === "number" && m.exit_price > 0 ? m.exit_price : null;
  const fill = typeof m.fill_price === "number" && m.fill_price > 0 ? m.fill_price : null;
  const entry = typeof m.entry_price === "number" && m.entry_price > 0 ? m.entry_price : null;
  if (exit != null && fill != null) return `вход $${fill.toFixed(2)} → выход $${exit.toFixed(2)}`;
  if (exit != null) return `выход $${exit.toFixed(2)}`;
  if (fill != null) return `вход $${fill.toFixed(2)}`;
  if (entry != null) return `ориентир $${entry.toFixed(2)}`;
  return "вход не зафиксирован";
}

export function holdingWindowLabelRu(key: string): string {
  const map: Record<string, string> = {
    скальп: "быстро",
    день: "день",
    свинг: "несколько дней",
    долго: "долго",
    scalp: "быстро",
    day: "день",
    swing: "несколько дней",
    long: "долго",
  };
  return map[key] ?? key;
}
