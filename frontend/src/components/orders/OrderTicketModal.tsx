"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { ordersApi } from "@/lib/api";
import { OrderTicket } from "./OrderTicket";
import { useIsMobile } from "@/hooks/useIsMobile";
import type { ManualOrder } from "@/types";

interface OrderTicketModalProps {
  ticker: string;
  maneuverId?: string;
  availableBalanceUsd?: number;
  onClose: () => void;
  onSubmitted?: (order: ManualOrder) => void;
}

export function OrderTicketModal({
  ticker,
  maneuverId,
  availableBalanceUsd,
  onClose,
  onSubmitted,
}: OrderTicketModalProps) {
  const { data: prefill, isLoading } = useQuery({
    queryKey: ["order-prefill", maneuverId],
    queryFn: () => ordersApi.prefillFromManeuver(maneuverId!),
    enabled: Boolean(maneuverId),
  });

  const isMobile = useIsMobile();
  const [confirmed, setConfirmed] = useState(false);

  const sheet = (
    <div
      className={
        isMobile
          ? "relative w-full max-h-[92vh] overflow-y-auto rounded-t-2xl border border-qa-border bg-qa-panel shadow-xl animate-in slide-in-from-bottom"
          : "relative w-full max-w-lg max-h-[90vh] overflow-y-auto rounded-xl border border-qa-border bg-qa-panel shadow-xl"
      }
    >
      <button
        type="button"
        onClick={onClose}
        className="absolute top-3 right-3 p-2 min-w-[44px] min-h-[44px] flex items-center justify-center rounded hover:bg-[var(--qa-hover)] text-qa-muted"
        aria-label="Close"
      >
        <X size={18} />
      </button>
      <div className="p-4 border-b border-qa-border">
        <h2 className="text-base font-semibold">Заявка — {ticker}</h2>
        <p className="text-xs text-qa-muted mt-1">
          Manual submission only. Review size, bracket, and type before sending.
        </p>
      </div>
      <div className="p-4 pb-8">
        {isLoading && maneuverId ? (
          <div className="text-sm text-qa-muted py-8 text-center">Загрузка заявки…</div>
        ) : (
          <>
            <OrderTicket
              ticker={ticker}
              prefill={prefill ?? null}
              availableBalanceUsd={availableBalanceUsd}
              onSubmitted={(order) => {
                onSubmitted?.(order);
                onClose();
              }}
            />
            {isMobile && (
              <button
                type="button"
                onClick={() => setConfirmed(true)}
                className="mt-4 w-full min-h-[48px] rounded-xl bg-terminal-accent text-black font-bold text-sm disabled:opacity-40"
                disabled={confirmed}
              >
                {confirmed ? "Review confirmed — submit order above" : "Tap to confirm order review"}
              </button>
            )}
          </>
        )}
      </div>
    </div>
  );

  if (isMobile) {
    return (
      <div className="fixed inset-0 z-50 flex flex-col justify-end bg-black/60">
        {sheet}
      </div>
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      {sheet}
    </div>
  );
}
