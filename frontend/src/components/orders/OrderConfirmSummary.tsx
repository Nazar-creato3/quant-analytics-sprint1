"use client";

import { clsx } from "clsx";
import type { OrderPreview } from "@/lib/order-preview";
import { formatPriceRange, formatUsd } from "@/lib/order-preview";

interface OrderConfirmSummaryProps {
  ticker: string;
  side: "buy" | "sell";
  preview: OrderPreview;
  /** Fat-finger: this panel is the confirmation moment (no second dialog). */
  confirmArmed?: boolean;
}

export function OrderConfirmSummary({ ticker, side, preview, confirmArmed }: OrderConfirmSummaryProps) {
  const verb = side === "buy" ? "Вы покупаете" : "Вы продаёте";
  const totalLabel = side === "buy" ? "Итого спишется" : "Итого зачислится";

  return (
    <div
      className={clsx(
        "rounded-md border px-2.5 py-2 text-[11px] space-y-1",
        confirmArmed
          ? "border-amber-500/70 bg-amber-500/10"
          : "border-qa-border bg-qa-panel-secondary/60",
      )}
      data-testid="order-confirm-summary"
    >
      {confirmArmed && (
        <p className="text-amber-300 text-[10px] font-medium uppercase tracking-wide">
          Подтверждение крупного ордера
        </p>
      )}
      <p className="text-white">
        {verb}: {preview.label} <span className="text-qa-muted">{ticker}</span>
      </p>
      <div className="flex justify-between gap-2 text-qa-muted">
        <span>Ожидаемая цена</span>
        <span className="tabular-nums text-white">{formatPriceRange(preview.fillLow, preview.fillHigh)}</span>
      </div>
      {!preview.complete && (
        <p className="text-amber-400/90 text-[10px]">
          В стакане не хватает глубины — оценка частичная ({preview.filledQty} из заявки)
        </p>
      )}
      <div className="flex justify-between gap-2 text-qa-muted">
        <span>Комиссия</span>
        <span className="tabular-nums text-white">~${formatUsd(preview.feeUsd)}</span>
      </div>
      <div className="flex justify-between gap-2 font-medium">
        <span>{totalLabel}</span>
        <span className="tabular-nums text-white">~${formatUsd(preview.totalUsd)}</span>
      </div>
    </div>
  );
}
