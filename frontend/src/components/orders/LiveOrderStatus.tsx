"use client";

import { clsx } from "clsx";

export type LiveOrderLike = {
  status: string;
  quantity: number;
  filled_qty?: number | null;
  filled_quantity?: number | null;
};

export function liveOrderPhase(order: LiveOrderLike): {
  label: string;
  tone: "pending" | "partial" | "done" | "cancel" | "other";
} {
  const filled = Number(order.filled_qty ?? order.filled_quantity ?? 0);
  const qty = Number(order.quantity) || 0;
  const st = (order.status || "").toLowerCase();

  if (["cancelled", "canceled", "rejected", "expired"].includes(st)) {
    return { label: "Отменён", tone: "cancel" };
  }
  if (["filled", "executed", "done"].includes(st) || (qty > 0 && filled >= qty - 1e-12)) {
    return { label: "Исполнен", tone: "done" };
  }
  if (filled > 0 && filled < qty) {
    return { label: `Частично исполнен (${fmtQty(filled)} из ${fmtQty(qty)})`, tone: "partial" };
  }
  if (["submitted", "new", "accepted", "open", "pending", "watching"].includes(st)) {
    return { label: "Отправлен", tone: "pending" };
  }
  return { label: order.status || "—", tone: "other" };
}

function fmtQty(n: number): string {
  if (n >= 1) return n.toFixed(n % 1 === 0 ? 0 : 4);
  return String(n);
}

export function LiveOrderStatusPill({ order }: { order: LiveOrderLike }) {
  const { label, tone } = liveOrderPhase(order);
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1 text-[10px] tabular-nums px-1.5 py-0.5 rounded",
        tone === "partial" && "text-amber-300 bg-amber-500/15",
        tone === "done" && "text-terminal-up bg-terminal-up/15",
        tone === "cancel" && "text-qa-muted bg-qa-panel-secondary",
        tone === "pending" && "text-sky-300 bg-sky-500/15",
        tone === "other" && "text-qa-muted",
      )}
      data-testid="live-order-status"
    >
      {tone === "partial" || tone === "pending" ? (
        <span className="inline-block w-1.5 h-1.5 rounded-full bg-current animate-pulse" />
      ) : null}
      {label}
    </span>
  );
}
