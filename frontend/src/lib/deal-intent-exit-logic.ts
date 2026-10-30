import type { DealIntent } from "@/types";

export type ExitLogicDraft = {
  stopLoss: string;
  takeProfit: string;
  trailingPct: string;
  partialClosePct: string;
  timeExitHours: string;
  positionSizeUsd: string;
};

export function exitPrice(exitLogic: Record<string, unknown>, key: "stop_loss" | "take_profit"): number | null {
  const block = exitLogic[key];
  if (block && typeof block === "object" && block !== null && "price" in block) {
    const price = Number((block as { price: unknown }).price);
    return Number.isFinite(price) && price > 0 ? price : null;
  }
  return null;
}

export function exitScalar(
  exitLogic: Record<string, unknown>,
  key: "trailing" | "partial_close",
  field: "pct",
): number | null {
  const block = exitLogic[key];
  if (block && typeof block === "object" && block !== null && field in block) {
    const value = Number((block as Record<string, unknown>)[field]);
    return Number.isFinite(value) ? value : null;
  }
  return null;
}

export function timeExitHours(exitLogic: Record<string, unknown>): number | null {
  const block = exitLogic.time_exit;
  if (block && typeof block === "object" && block !== null && "hours" in block) {
    const hours = Number((block as { hours: unknown }).hours);
    return Number.isFinite(hours) && hours > 0 ? hours : null;
  }
  return null;
}

export function positionSizeFromExit(exitLogic: Record<string, unknown>): number | null {
  const raw = exitLogic.position_size_usd;
  const value = typeof raw === "number" ? raw : Number(raw);
  return Number.isFinite(value) && value > 0 ? value : null;
}

export function draftsFromIntent(intent: DealIntent): ExitLogicDraft {
  const el = intent.exit_logic ?? {};
  return {
    stopLoss: exitPrice(el, "stop_loss")?.toString() ?? "",
    takeProfit: exitPrice(el, "take_profit")?.toString() ?? "",
    trailingPct: exitScalar(el, "trailing", "pct")?.toString() ?? "",
    partialClosePct: exitScalar(el, "partial_close", "pct")?.toString() ?? "",
    timeExitHours: timeExitHours(el)?.toString() ?? "",
    positionSizeUsd: positionSizeFromExit(el)?.toString() ?? "",
  };
}

export function buildExitLogicPatch(draft: ExitLogicDraft): Record<string, unknown> {
  const patch: Record<string, unknown> = {};
  const sl = draft.stopLoss.trim() ? parseFloat(draft.stopLoss) : null;
  const tp = draft.takeProfit.trim() ? parseFloat(draft.takeProfit) : null;
  const trail = draft.trailingPct.trim() ? parseFloat(draft.trailingPct) : null;
  const partial = draft.partialClosePct.trim() ? parseFloat(draft.partialClosePct) : null;
  const hours = draft.timeExitHours.trim() ? parseFloat(draft.timeExitHours) : null;
  const size = draft.positionSizeUsd.trim() ? parseFloat(draft.positionSizeUsd) : null;

  if (sl != null && Number.isFinite(sl) && sl > 0) patch.stop_loss = { price: sl };
  if (tp != null && Number.isFinite(tp) && tp > 0) patch.take_profit = { price: tp };
  if (trail != null && Number.isFinite(trail) && trail >= 0) patch.trailing = { pct: trail };
  if (partial != null && Number.isFinite(partial) && partial > 0 && partial <= 100) {
    patch.partial_close = { pct: partial };
  }
  if (hours != null && Number.isFinite(hours) && hours > 0) patch.time_exit = { hours };
  if (size != null && Number.isFinite(size) && size > 0) patch.position_size_usd = size;

  return patch;
}

export const OPEN_DEAL_INTENT_STATUSES = new Set(["approved", "executing", "filled"]);

export const PENDING_DEAL_INTENT_EDIT_STATUSES = new Set(["draft", "pending_approval", "held"]);
