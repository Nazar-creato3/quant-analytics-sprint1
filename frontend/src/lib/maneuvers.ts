import type { Maneuver, ManeuverReport } from "@/types";
import { isPendingApproval } from "@/lib/approval";

/** Maneuvers visible in Positions tab — matches backend OPEN_EXPOSURE_STATUSES. */
export const OPEN_POSITION_STATUS_FILTER = "approved,filled,executing";

/** Completed / closed paper positions (realized P&L). */
export const CLOSED_POSITION_STATUS_FILTER = "closed";

/** Maneuvers awaiting operator decision (Orders tab). */
export const PENDING_ORDER_STATUS_FILTER = "pending,pending_approval,awaiting_approval";

/** Standard toast after decision-only approve (no auto-execution). */
export const MANEUVER_APPROVED_TOAST =
  "Идея одобрена и появилась в позициях";

export const CANCELLABLE_MANEUVER_STATUSES = new Set([
  "pending",
  "approved",
  "executing",
  "filled",
]);

export function isManeuverCancellable(status: string | undefined): boolean {
  return !!status && CANCELLABLE_MANEUVER_STATUSES.has(status);
}

/** Tradeable slot — matches backend StrategyType and generator output. */
export function isTradeableManeuver(m: Maneuver): boolean {
  if (m.strategy_type === "no_trade") return false;
  if (!m.ticker || m.ticker === "—" || m.ticker === "-") return false;
  if (m.direction === "neutral") return false;
  if (!Number.isFinite(m.position_size_usd) || m.position_size_usd <= 0) return false;
  return true;
}

export function countTradeableManeuvers(maneuvers: Maneuver[] | undefined): number {
  return (maneuvers ?? []).filter(isTradeableManeuver).length;
}

/** Pending approval rows that are still tradeable (toast should prefer this over report total). */
export function countPendingTradeableManeuvers(maneuvers: Maneuver[] | undefined): number {
  return (maneuvers ?? []).filter((m) => isPendingApproval(m.status) && isTradeableManeuver(m)).length;
}

/** Format a single USD leg for Income column (avoid `-0` and silent round-to-zero). */
function formatIncomeUsd(value: number): string {
  const v = Object.is(value, -0) ? 0 : value;
  const abs = Math.abs(v);
  if (abs >= 1000) return Math.round(v).toLocaleString("en");
  if (abs >= 10) return Math.round(v).toLocaleString("en");
  if (abs >= 1) return v.toFixed(1);
  return v.toFixed(2);
}

/** Dollar P&L range aligned with model + horizon (not full TP). */
export function formatManeuverIncomeRange(m: Maneuver): string {
  if (m.expected_pnl_low != null && m.expected_pnl_high != null) {
    const lo = m.expected_pnl_low;
    const hi = m.expected_pnl_high;
    const loStr = formatIncomeUsd(lo);
    const hiStr = formatIncomeUsd(hi);
    let out = `$${loStr} – $${hiStr}`;
    if (
      m.expected_return_low != null &&
      m.expected_return_high != null &&
      (Math.abs(lo) < 1 || Math.abs(hi) < 1)
    ) {
      out += ` (${m.expected_return_low.toFixed(1)}–${m.expected_return_high.toFixed(1)}%)`;
    }
    return out;
  }
  if (
    m.expected_return_low != null &&
    m.expected_return_high != null &&
    m.position_size_usd > 0
  ) {
    const lo = m.position_size_usd * (m.expected_return_low / 100);
    const hi = m.position_size_usd * (m.expected_return_high / 100);
    return `$${formatIncomeUsd(lo)} – $${formatIncomeUsd(hi)} (${m.expected_return_low.toFixed(1)}–${m.expected_return_high.toFixed(1)}%)`;
  }
  return "—";
}

export function formatManeuverSlotHeadline(report: ManeuverReport): {
  title: string;
  subtitleTradeable: string;
} {
  const ctx = report.market_context ?? {};
  const slots = Number(ctx.maneuver_slots ?? 10);
  const threshold = typeof ctx.confidence_threshold === "number" ? ctx.confidence_threshold : null;
  const rows = report.maneuvers.filter(isTradeableManeuver);
  const tradeableFromRows = rows.length;
  const aboveFromRows =
    threshold != null
      ? rows.filter((m) => m.confidence >= threshold - 1e-9).length
      : tradeableFromRows;
  const backfillFromRows = Math.max(0, tradeableFromRows - aboveFromRows);

  const thresholdPct = threshold != null ? `${Math.round(threshold * 100)}%` : null;

  let title: string;
  if (aboveFromRows > 0 && thresholdPct) {
    title = `${aboveFromRows} из ${slots} слотов ≥ ${thresholdPct}`;
  } else if (tradeableFromRows > 0 && thresholdPct) {
    title = `${tradeableFromRows} из ${slots} слотов (лучшие доступные)`;
  } else if (tradeableFromRows > 0) {
    title = `${tradeableFromRows} из ${slots} инвестиционных слотов`;
  } else {
    title = `0 торгуемых из ${slots} слотов`;
  }

  const subtitleTradeable =
    backfillFromRows > 0 && thresholdPct
      ? `${aboveFromRows}/${slots} ≥ ${thresholdPct} · +${backfillFromRows} ниже порога`
      : `${tradeableFromRows}/${slots}`;

  return { title, subtitleTradeable };
}

export function pipelineToastBackfillHint(report: ManeuverReport | undefined): {
  aboveThreshold: number;
  backfillCount: number;
  thresholdPct: number | null;
} | null {
  if (!report?.maneuvers?.length) return null;
  const ctx = report.market_context ?? {};
  const threshold =
    typeof ctx.confidence_threshold === "number" ? ctx.confidence_threshold : null;
  const rows = report.maneuvers.filter(isTradeableManeuver);
  const above =
    threshold != null
      ? rows.filter((m) => m.confidence >= threshold - 1e-9).length
      : rows.length;
  const backfill = Math.max(0, rows.length - above);
  if (backfill <= 0) return null;
  return {
    aboveThreshold: above,
    backfillCount: backfill,
    thresholdPct: threshold != null ? Math.round(threshold * 100) : null,
  };
}

export function formatPipelineManeuverToast(
  tradeableCount?: number | null,
  maneuverSlots?: number | null,
  pendingApprovalCount?: number | null,
  backfillHint?: {
    aboveThreshold: number;
    backfillCount: number;
    thresholdPct: number | null;
  } | null,
): string {
  const slots = maneuverSlots ?? 10;
  const inReport = tradeableCount ?? 0;
  const pending =
    pendingApprovalCount != null && Number.isFinite(pendingApprovalCount)
      ? pendingApprovalCount
      : inReport;

  if (inReport <= 0) {
    return `Анализ завершён — торгуемых маневров нет (0/${slots})`;
  }

  const backfillSuffix =
    backfillHint &&
    backfillHint.backfillCount > 0 &&
    backfillHint.aboveThreshold === 0 &&
    backfillHint.thresholdPct != null
      ? ` · все ${backfillHint.backfillCount} ниже порога ${backfillHint.thresholdPct}%`
      : backfillHint && backfillHint.backfillCount > 0 && backfillHint.aboveThreshold > 0
        ? ` · +${backfillHint.backfillCount} ниже порога`
        : "";

  if (pending <= 0) {
    return `Анализ завершён — в отчёте ${inReport}/${slots} торгуемых, ожидают одобрения: 0 (уже отклонены или исполнены)${backfillSuffix}`;
  }
  if (pending === inReport) {
    return `Анализ завершён — ${pending}/${slots} маневров ожидают одобрения${backfillSuffix}`;
  }
  return `Анализ завершён — ${pending}/${slots} ожидают одобрения (в отчёте ${inReport} торгуемых)${backfillSuffix}`;
}

export const MANEUVER_CANCEL_QUERY_KEYS = [
  "decision-feed-latest-report",
  "decision-feed-reports",
  "pending-approvals",
  "pending-deal-intents",
  "bottom-orders",
  "bottom-positions",
  "bottom-fills",
  "bottom-manual-orders",
  "portfolio-metrics",
  "maneuvers-open-positions",
  "decision-feed-maneuvers",
] as const;
